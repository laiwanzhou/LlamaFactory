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

import json
import os
from pathlib import Path

from jrt_pipeline.cli import main
from jrt_pipeline.extraction import table_a1
from jrt_pipeline.hashing import file_sha256


class FakeRenderer:
    version = "fake-1"

    def render(self, pdf_path: Path, physical_page: int, output_path: Path) -> None:
        output_path.write_bytes(b"png")


def test_candidate_command_stops_at_awaiting_review(synthetic_pdf: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(table_a1.PopplerPageRenderer, "from_environment", lambda: FakeRenderer())
    monkeypatch.setenv("JRT0197_NODE", os.environ["JRT0197_NODE"])
    monkeypatch.setenv("JRT0197_NODE_MODULES", os.environ["JRT0197_NODE_MODULES"])
    runtime_root = tmp_path / "runtime"
    exit_code = main(
        [
            "candidate",
            "--pdf",
            str(synthetic_pdf),
            "--runtime-root",
            str(runtime_root),
            "--run-id",
            "synthetic-001",
        ]
    )
    assert exit_code == 0
    candidate = runtime_root / "candidate" / "synthetic-001"
    manifest = json.loads((candidate / "jrt0197_rule_candidate_manifest.json").read_text(encoding="utf-8"))
    assert manifest["pipeline_state"] == "awaiting_review"
    assert manifest["page_count"] == 35
    assert len(list((candidate / "evidence" / "pages").glob("*.png"))) == 35
    assert not (runtime_root / "frozen").exists()
    assert not (runtime_root / "datasets").exists()
    before = (candidate / "jrt0197_rule_master_candidate.jsonl").read_bytes()
    assert (
        main(
            [
                "candidate",
                "--pdf",
                str(synthetic_pdf),
                "--runtime-root",
                str(runtime_root),
                "--run-id",
                "synthetic-001",
            ]
        )
        != 0
    )
    assert (candidate / "jrt0197_rule_master_candidate.jsonl").read_bytes() == before


def test_standalone_stages_match_combined_core_artifacts(synthetic_pdf: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(table_a1.PopplerPageRenderer, "from_environment", lambda: FakeRenderer())
    extracted = tmp_path / "extracted"
    validated = tmp_path / "validated"
    standalone = tmp_path / "standalone"
    comparison_root = tmp_path / "comparison-root"
    assert (
        main(["extract", "--pdf", str(synthetic_pdf), "--output", str(extracted), "--artifact-id", "same:extracted"])
        == 0
    )
    assert (
        main(
            [
                "validate",
                "--input",
                str(extracted),
                "--output",
                str(validated),
                "--artifact-id",
                "same:validated",
                "--runtime-root",
                str(comparison_root),
            ]
        )
        == 0
    )
    assert main(["build-review", "--input", str(validated), "--output", str(standalone), "--run-id", "same"]) == 0
    combined_root = tmp_path / "combined-root"
    assert (
        main(
            [
                "candidate",
                "--pdf",
                str(synthetic_pdf),
                "--runtime-root",
                str(combined_root),
                "--run-id",
                "same",
                "--source-date-epoch",
                "1784769600",
            ]
        )
        == 0
    )
    combined = combined_root / "candidate" / "same"
    standalone_hashes = {
        path.relative_to(standalone).as_posix(): file_sha256(path) for path in standalone.rglob("*") if path.is_file()
    }
    combined_hashes = {
        path.relative_to(combined).as_posix(): file_sha256(path)
        for path in combined.rglob("*")
        if path.is_file() and path.name != "run_metadata.json"
    }
    assert standalone_hashes == combined_hashes
