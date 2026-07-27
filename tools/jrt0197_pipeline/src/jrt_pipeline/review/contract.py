# Copyright 2025 HuggingFace Inc. and the LlamaFactory team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..contracts import read_json, read_jsonl
from ..hashing import file_sha256, sha256_bytes

EDITABLE_COLUMNS = (
    "class1",
    "class2",
    "class2_definition",
    "class3",
    "class3_definition",
    "class4",
    "class4_description",
    "minimum_security_level",
    "note",
    "source_structure_decision",
    "lineage_decision",
    "prior_rule_ids",
    "retained_rule_id",
    "review_decision",
    "review_comment",
    "reviewer",
    "reviewed_at",
)


@dataclass(frozen=True)
class WorkbookRuntime:
    node_executable: Path
    node_modules_root: Path
    artifact_tool_version: str

    @classmethod
    def from_environment(cls) -> WorkbookRuntime:
        node = os.getenv("JRT0197_NODE") or shutil.which("node.exe") or shutil.which("node")
        modules = os.getenv("JRT0197_NODE_MODULES")
        if not node or not modules:
            raise RuntimeError("JRT0197_NODE and JRT0197_NODE_MODULES must identify the bundled workbook runtime")
        package = Path(modules) / "@oai" / "artifact-tool" / "package.json"
        if not package.is_file():
            raise RuntimeError(f"@oai/artifact-tool is missing below {modules}")
        version = json.loads(package.read_text(encoding="utf-8"))["version"]
        return cls(Path(node), Path(modules), str(version))


def _json_cell(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_review_contract(validated_dir: Path) -> dict[str, object]:
    master_path = validated_dir / "jrt0197_rule_master_candidate.jsonl"
    manifest_path = validated_dir / "jrt0197_rule_candidate_manifest.json"
    records = read_jsonl(master_path)
    report = read_json(validated_dir / "jrt0197_rule_validation_report.json")
    diff = read_json(validated_dir / "jrt0197_rule_diff.json")
    manifest = read_json(manifest_path)
    review_records: list[dict[str, object]] = []
    for record in records:
        review_records.append(
            {
                "candidate_id": record["candidate_id"],
                "source_order": record["source_order"],
                "source_physical_page": record["source_physical_page"],
                "source_physical_page_start": record.get("source_physical_page_start"),
                "source_physical_page_end": record.get("source_physical_page_end"),
                "source_row_locator": record.get("source_row_locator"),
                "class1": record.get("class1"),
                "class2": record.get("class2"),
                "class2_definition": record.get("class2_definition"),
                "class3": record.get("class3"),
                "class3_definition": record.get("class3_definition"),
                "class4": record.get("class4"),
                "class4_description": record.get("class4_description"),
                "minimum_security_level": record.get("minimum_security_level"),
                "note": record.get("note"),
                "raw_extraction": _json_cell(record.get("raw_extraction")),
                "normalized_content": _json_cell(record.get("normalized_content")),
                "inheritance_trace": _json_cell(record.get("inheritance_trace")),
                "candidate_fingerprint": record.get("candidate_fingerprint"),
                "validation_flags": _json_cell(record.get("validation_flags")),
                "source_structure_decision": None,
                "lineage_decision": None,
                "prior_rule_ids": None,
                "retained_rule_id": None,
                "review_decision": None,
                "review_comment": None,
                "reviewer": None,
                "reviewed_at": None,
            }
        )
    ids = sorted(str(record["candidate_id"]) for record in records)
    id_set_hash = sha256_bytes(_json_cell(ids).encode("utf-8"))
    metadata = {
        "run_id": manifest["run_id"],
        "candidate_jsonl_sha256": file_sha256(master_path),
        "manifest_sha256": file_sha256(manifest_path),
        "review_schema_version": "1.0.0",
        "editable_columns": list(EDITABLE_COLUMNS),
        "candidate_id_count": len(ids),
        "candidate_id_set_hash": id_set_hash,
    }
    return {
        "schema_name": "jrt0197_review_contract",
        "schema_version": "1.0.0",
        "run_id": manifest["run_id"],
        "diagnostic_only": report["validation_status"] != "passed",
        "editable_columns": list(EDITABLE_COLUMNS),
        "metadata": metadata,
        "records": review_records,
        "findings": report["findings"],
        "diff": diff,
        "statistics": {
            "record_count": report["record_count"],
            "level_distribution": report["level_distribution"],
            "error_count": report["error_count"],
            "warning_count": report["warning_count"],
            "info_count": report["info_count"],
        },
    }


@contextmanager
def _module_resolution_link(project_root: Path, modules_root: Path) -> Iterator[None]:
    link = project_root / "node_modules"
    created = False
    if not link.exists():
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(modules_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        created = True
    try:
        yield
    finally:
        if created:
            os.rmdir(link)


def invoke_workbook_builder(
    contract_path: Path,
    output_path: Path,
    preview_dir: Path,
    runtime: WorkbookRuntime,
) -> None:
    if tuple(part.casefold() for part in preview_dir.parts[-2:]) != ("previews", "workbook"):
        raise ValueError("workbook previews must be written below previews/workbook")
    project_root = Path(__file__).resolve().parents[3]
    builder = project_root / "tools" / "build_review.mjs"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    with _module_resolution_link(project_root, runtime.node_modules_root):
        result = subprocess.run(
            [
                str(runtime.node_executable),
                str(builder),
                "--contract",
                str(contract_path),
                "--workbook",
                str(output_path),
                "--preview-dir",
                str(preview_dir),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    if not output_path.is_file():
        raise RuntimeError("workbook builder did not create the workbook")
