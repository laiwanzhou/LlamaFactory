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

import argparse
import json
import platform
import re
import shutil
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from .contracts import (
    CandidateManifest,
    PageEvidence,
    RuleCandidate,
    load_schema,
    object_schema,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl,
)
from .extraction.table_a1 import (
    EXTRACTION_VERSION,
    FINGERPRINT_VERSION,
    PageEvidenceSummary,
    PopplerPageRenderer,
    assemble_candidates,
    extract_page_evidence,
    write_page_evidence,
)
from .hashing import file_sha256
from .review.contract import WorkbookRuntime, build_review_contract, invoke_workbook_builder
from .runtime import ArtifactExistsError, atomic_artifact_dir
from .validation.rules import diff_candidates, validate_candidates

COMMANDS = (
    "extract",
    "validate",
    "build-review",
    "freeze",
    "generate-rule-sft",
    "generate-field-master",
    "generate-field-sft",
    "audit",
    "candidate",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jrt0197-pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("freeze")
    commands.add_parser("generate-rule-sft")
    commands.add_parser("generate-field-master")
    commands.add_parser("generate-field-sft")
    commands.add_parser("audit")
    extract = commands.add_parser("extract")
    extract.add_argument("--pdf", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)
    extract.add_argument("--artifact-id", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    validate.add_argument("--artifact-id", required=True)
    validate.add_argument("--runtime-root", type=Path, required=True)
    review = commands.add_parser("build-review")
    review.add_argument("--input", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--run-id", required=True)
    candidate = commands.add_parser("candidate")
    candidate.add_argument("--pdf", type=Path, required=True)
    candidate.add_argument("--runtime-root", type=Path, required=True)
    candidate.add_argument("--run-id", required=True)
    candidate.add_argument("--source-date-epoch", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "candidate":
            return _run_candidate(args.pdf, args.runtime_root, args.run_id, args.source_date_epoch)
        if args.command == "extract":
            return _run_extract(args.pdf, args.output, args.artifact_id)
        if args.command == "validate":
            return _run_validate(args.input, args.output, args.artifact_id, args.runtime_root)
        if args.command == "build-review":
            return _run_build_review(args.input, args.output, args.run_id)
        print(json.dumps({"code": "not_implemented", "command": args.command}, ensure_ascii=False), file=sys.stderr)
        return 3
    except ArtifactExistsError as error:
        print(json.dumps({"code": "artifact_exists", "path": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 4
    except Exception as error:
        print(json.dumps({"code": "pipeline_failed", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


def _validate_inputs(pdf_path: Path, runtime_root: Path, run_id: str) -> None:
    if not pdf_path.is_absolute() or not runtime_root.is_absolute():
        raise ValueError("PDF and runtime root must be absolute paths")
    if not pdf_path.is_file():
        raise FileNotFoundError(str(pdf_path))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", run_id):
        raise ValueError("run ID contains unsupported path characters")


def _tool_versions(renderer_version: str, workbook: WorkbookRuntime | None = None) -> dict[str, str]:
    values = {
        "python": platform.python_version(),
        "pdfplumber": metadata.version("pdfplumber"),
        "pypdf": metadata.version("pypdf"),
        "poppler": renderer_version,
    }
    if workbook:
        values["node"] = "24.14.0"
        values["artifact_tool"] = workbook.artifact_tool_version
    return values


def _manifest(
    *,
    artifact_id: str,
    run_id: str,
    state: str,
    source_pdf_sha256: str,
    candidate_jsonl_sha256: str,
    evidence_summary,
    records,
    comparison: dict[str, object],
    validation_status: str,
    tool_versions: dict[str, str],
    parent_artifact_id: str | None = None,
    parent_hash: str | None = None,
    workbook_sha256: str | None = None,
    preview_count: int = 0,
) -> CandidateManifest:
    distribution = Counter(
        str(record.minimum_security_level) for record in records if record.minimum_security_level is not None
    )
    return CandidateManifest(
        schema_name="jrt0197_rule_candidate_manifest",
        schema_version="1.0.0",
        artifact_id=artifact_id,
        run_id=run_id,
        pipeline_state=state,
        source_pdf_sha256=source_pdf_sha256,
        candidate_jsonl_sha256=candidate_jsonl_sha256,
        page_evidence_jsonl_sha256=evidence_summary.page_evidence_jsonl_sha256,
        page_png_set_sha256=evidence_summary.page_png_set_sha256,
        page_count=evidence_summary.page_count,
        ownership_block_count=evidence_summary.ownership_block_count,
        unassigned_block_count=evidence_summary.unassigned_block_count,
        extraction_version=EXTRACTION_VERSION,
        normalization_version="1.0.0",
        fingerprint_version=FINGERPRINT_VERSION,
        tool_versions=tool_versions,
        physical_page_start=17,
        physical_page_end=51,
        record_count=len(records),
        level_distribution=dict(sorted(distribution.items())),
        comparison_baseline=comparison,
        validation_status=validation_status,
        parent_artifact_id=parent_artifact_id,
        parent_artifact_manifest_sha256=parent_hash,
        workbook_sha256=workbook_sha256,
        preview_count=preview_count,
    )


def _write_manifest(path: Path, manifest: CandidateManifest) -> str:
    return write_json(path, manifest.to_mapping(), load_schema("candidate-manifest-1.0.0"))


def _extract_into(pdf_path: Path, directory: Path, artifact_id: str, run_id: str):
    renderer = PopplerPageRenderer.from_environment()
    pages = extract_page_evidence(pdf_path, 17, 51, renderer=renderer)
    records = assemble_candidates(pages, run_id)
    evidence_summary = write_page_evidence(pages, directory / "evidence")
    candidate_hash = write_jsonl(
        directory / "jrt0197_rule_master_candidate.jsonl",
        [record.to_mapping() for record in records],
        load_schema("rule-candidate-1.0.0"),
    )
    source_hash = file_sha256(pdf_path)
    manifest = _manifest(
        artifact_id=artifact_id,
        run_id=run_id,
        state="extracted",
        source_pdf_sha256=source_hash,
        candidate_jsonl_sha256=candidate_hash,
        evidence_summary=evidence_summary,
        records=records,
        comparison={"baseline_status": "not_evaluated"},
        validation_status="not_run",
        tool_versions=_tool_versions(renderer.version),
    )
    return pages, records, evidence_summary, manifest


def _run_extract(pdf_path: Path, output: Path, artifact_id: str) -> int:
    _validate_inputs(pdf_path, output.parent, artifact_id.replace(":", "-"))
    with atomic_artifact_dir(output) as staging:
        _, _, _, manifest = _extract_into(pdf_path, staging, artifact_id, artifact_id.split(":", 1)[0])
        _write_manifest(staging / "jrt0197_rule_candidate_manifest.json", manifest)
    return 0


def _run_validate(input_dir: Path, output: Path, artifact_id: str, runtime_root: Path) -> int:
    input_manifest_path = input_dir / "jrt0197_rule_candidate_manifest.json"
    input_manifest = CandidateManifest.from_mapping(read_json(input_manifest_path))
    if input_manifest.pipeline_state != "extracted":
        raise ValueError("validate requires an extracted artifact")
    _verify_stage_hashes(input_dir, input_manifest)
    records = [
        RuleCandidate.from_mapping(value) for value in read_jsonl(input_dir / "jrt0197_rule_master_candidate.jsonl")
    ]
    pages = [
        PageEvidence.from_mapping(value)
        for value in read_jsonl(input_dir / "evidence" / "jrt0197_page_evidence.jsonl")
    ]
    summary = _summary_from_manifest(input_manifest)
    with atomic_artifact_dir(output) as staging:
        shutil.copytree(input_dir, staging, dirs_exist_ok=True)
        lineage = staging / "lineage"
        lineage.mkdir(exist_ok=True)
        shutil.copy2(input_manifest_path, lineage / "extracted_manifest.json")
        diff = diff_candidates(records, runtime_root)
        comparison = _comparison_from_diff(diff)
        report = validate_candidates(records, pages, page_start=17, page_end=51, comparison=comparison)
        write_json(staging / "jrt0197_rule_validation_report.json", report, load_schema("validation-report-1.0.0"))
        write_json(staging / "jrt0197_rule_diff.json", diff, load_schema("rule-diff-1.0.0"))
        workbook_runtime = WorkbookRuntime.from_environment()
        validated = _manifest(
            artifact_id=artifact_id,
            run_id=input_manifest.run_id,
            state="validated" if report["validation_status"] == "passed" else "validation_failed",
            source_pdf_sha256=input_manifest.source_pdf_sha256,
            candidate_jsonl_sha256=input_manifest.candidate_jsonl_sha256,
            evidence_summary=summary,
            records=records,
            comparison=comparison,
            validation_status=str(report["validation_status"]),
            tool_versions=_tool_versions(input_manifest.tool_versions["poppler"], workbook_runtime),
            parent_artifact_id=input_manifest.artifact_id,
            parent_hash=file_sha256(input_manifest_path),
        )
        _write_manifest(staging / "jrt0197_rule_candidate_manifest.json", validated)
    return 0 if report["validation_status"] == "passed" else 2


def _run_build_review(input_dir: Path, output: Path, run_id: str) -> int:
    input_manifest_path = input_dir / "jrt0197_rule_candidate_manifest.json"
    input_manifest = CandidateManifest.from_mapping(read_json(input_manifest_path))
    if input_manifest.pipeline_state not in {"validated", "validation_failed"}:
        raise ValueError("build-review requires a validated or validation_failed artifact")
    _verify_stage_hashes(input_dir, input_manifest)
    with atomic_artifact_dir(output) as staging:
        shutil.copytree(input_dir, staging, dirs_exist_ok=True)
        lineage = staging / "lineage"
        lineage.mkdir(exist_ok=True)
        shutil.copy2(input_manifest_path, lineage / "validated_manifest.json")
        workbook_runtime = WorkbookRuntime.from_environment()
        contract = build_review_contract(staging)
        contract_path = staging / ".review-contract.json"
        write_json(contract_path, contract, load_schema("review-contract-1.0.0"))
        invoke_workbook_builder(
            contract_path,
            staging / "jrt0197_rule_review.xlsx",
            staging / "previews" / "workbook",
            workbook_runtime,
        )
        contract_path.unlink()
        final = replace(
            input_manifest,
            artifact_id=run_id,
            run_id=run_id,
            pipeline_state="awaiting_review" if input_manifest.validation_status == "passed" else "validation_failed",
            parent_artifact_id=input_manifest.artifact_id,
            parent_artifact_manifest_sha256=file_sha256(input_manifest_path),
            workbook_sha256=file_sha256(staging / "jrt0197_rule_review.xlsx"),
            preview_count=len(list((staging / "previews" / "workbook").glob("*.png"))),
        )
        _write_manifest(staging / "jrt0197_rule_candidate_manifest.json", final)
        _verify_candidate(staging, final)
    return 0 if final.pipeline_state == "awaiting_review" else 2


def _verify_stage_hashes(directory: Path, manifest: CandidateManifest) -> None:
    if file_sha256(directory / "jrt0197_rule_master_candidate.jsonl") != manifest.candidate_jsonl_sha256:
        raise RuntimeError("candidate JSONL hash mismatch")
    if file_sha256(directory / "evidence" / "jrt0197_page_evidence.jsonl") != manifest.page_evidence_jsonl_sha256:
        raise RuntimeError("page evidence JSONL hash mismatch")


def _summary_from_manifest(manifest: CandidateManifest) -> PageEvidenceSummary:
    return PageEvidenceSummary(
        page_count=manifest.page_count,
        ownership_block_count=manifest.ownership_block_count,
        unassigned_block_count=manifest.unassigned_block_count,
        page_evidence_jsonl_sha256=manifest.page_evidence_jsonl_sha256,
        page_png_set_sha256=manifest.page_png_set_sha256,
    )


def _comparison_from_diff(diff: dict[str, object]) -> dict[str, object]:
    return {
        "baseline_type": diff["baseline_type"],
        "baseline_status": diff["baseline_status"],
        "baseline_id": diff["baseline_id"],
        "baseline_hash": diff["baseline_hash"],
        "record_count_change": diff["record_count_change"],
        "level_distribution_change": diff["level_distribution_change"],
    }


def _run_candidate(pdf_path: Path, runtime_root: Path, run_id: str, source_date_epoch: int | None) -> int:
    _validate_inputs(pdf_path, runtime_root, run_id)
    target = runtime_root / "candidate" / run_id
    with atomic_artifact_dir(target) as staging:
        pages, records, evidence_summary, extracted = _extract_into(pdf_path, staging, f"{run_id}:extracted", run_id)
        lineage = staging / "lineage"
        lineage.mkdir()
        extracted_hash = _write_manifest(lineage / "extracted_manifest.json", extracted)
        diff = diff_candidates(records, runtime_root)
        comparison = _comparison_from_diff(diff)
        report = validate_candidates(records, pages, page_start=17, page_end=51, comparison=comparison)
        write_json(staging / "jrt0197_rule_validation_report.json", report, load_schema("validation-report-1.0.0"))
        write_json(staging / "jrt0197_rule_diff.json", diff, load_schema("rule-diff-1.0.0"))
        workbook_runtime = WorkbookRuntime.from_environment()
        validated_state = "validated" if report["validation_status"] == "passed" else "validation_failed"
        validated = _manifest(
            artifact_id=f"{run_id}:validated",
            run_id=run_id,
            state=validated_state,
            source_pdf_sha256=extracted.source_pdf_sha256,
            candidate_jsonl_sha256=extracted.candidate_jsonl_sha256,
            evidence_summary=evidence_summary,
            records=records,
            comparison=comparison,
            validation_status=str(report["validation_status"]),
            tool_versions=_tool_versions(extracted.tool_versions["poppler"], workbook_runtime),
            parent_artifact_id=extracted.artifact_id,
            parent_hash=extracted_hash,
        )
        validated_hash = _write_manifest(lineage / "validated_manifest.json", validated)
        _write_manifest(staging / "jrt0197_rule_candidate_manifest.json", validated)
        contract = build_review_contract(staging)
        contract_path = staging / ".review-contract.json"
        write_json(contract_path, contract, load_schema("review-contract-1.0.0"))
        invoke_workbook_builder(
            contract_path,
            staging / "jrt0197_rule_review.xlsx",
            staging / "previews" / "workbook",
            workbook_runtime,
        )
        contract_path.unlink()
        final_state = "awaiting_review" if report["validation_status"] == "passed" else "validation_failed"
        final = replace(
            validated,
            artifact_id=run_id,
            pipeline_state=final_state,
            parent_artifact_id=validated.artifact_id,
            parent_artifact_manifest_sha256=validated_hash,
            workbook_sha256=file_sha256(staging / "jrt0197_rule_review.xlsx"),
            preview_count=len(list((staging / "previews" / "workbook").glob("*.png"))),
        )
        _write_manifest(staging / "jrt0197_rule_candidate_manifest.json", final)
        run_metadata = {
            "run_id": run_id,
            "generated_at": datetime.fromtimestamp(source_date_epoch, UTC).isoformat()
            if source_date_epoch is not None
            else datetime.now(UTC).isoformat(),
            "command": "candidate",
            "host_python": sys.executable,
        }
        write_json(staging / "run_metadata.json", run_metadata, object_schema(list(run_metadata)))
        _verify_candidate(staging, final)
    if final.pipeline_state != "awaiting_review":
        print(
            json.dumps(
                {"code": "candidate_validation_failed", "error_count": report["error_count"], "path": str(target)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps({"pipeline_state": final.pipeline_state, "run_id": run_id, "path": str(target)}, ensure_ascii=False)
    )
    return 0


def _verify_candidate(directory: Path, manifest: CandidateManifest) -> None:
    if file_sha256(directory / "jrt0197_rule_master_candidate.jsonl") != manifest.candidate_jsonl_sha256:
        raise RuntimeError("candidate JSONL hash verification failed")
    if file_sha256(directory / "evidence" / "jrt0197_page_evidence.jsonl") != manifest.page_evidence_jsonl_sha256:
        raise RuntimeError("page evidence JSONL hash verification failed")
    if len(list((directory / "evidence" / "pages").glob("physical-page-*.png"))) != 35:
        raise RuntimeError("exactly 35 physical-page evidence images are required")
    if manifest.preview_count != 6:
        raise RuntimeError("all six user-facing workbook previews are required")
    for forbidden in ("frozen", "datasets"):
        if (directory / forbidden).exists():
            raise RuntimeError(f"forbidden artifact directory exists: {forbidden}")
