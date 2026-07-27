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

from dataclasses import replace
from pathlib import Path

from jrt_pipeline.extraction.table_a1 import assemble_candidates, extract_page_evidence
from jrt_pipeline.validation.rules import diff_candidates, validate_candidates


class FakeRenderer:
    version = "fake-1"

    def render(self, pdf_path: Path, physical_page: int, output_path: Path) -> None:
        output_path.write_bytes(b"png")


def test_blocking_rule_findings(synthetic_pdf: Path, tmp_path: Path) -> None:
    pages = extract_page_evidence(synthetic_pdf, 17, 19, renderer=FakeRenderer())
    records = assemble_candidates(pages, "test")
    records[0] = replace(records[0], minimum_security_level=5)
    records[-1] = replace(records[-1], class4=None, path_depth=3, source_structure_status="unconfirmed_missing_class4")
    report = validate_candidates(records, pages, page_start=17, page_end=19)
    codes = {(finding["severity"], finding["code"]) for finding in report["findings"]}
    assert ("error", "level_out_of_scope") in codes
    assert ("error", "missing_class4_from_source") in codes
    assert report["validation_status"] == "failed"
    assert report["error_count"] == 2


def test_diff_reports_no_baseline(tmp_path: Path, synthetic_pdf: Path) -> None:
    pages = extract_page_evidence(synthetic_pdf, 17, 19, renderer=FakeRenderer())
    records = assemble_candidates(pages, "test")
    diff = diff_candidates(records, tmp_path)
    assert diff["baseline_type"] is None
    assert diff["baseline_status"] == "no_baseline"
    assert diff["added_count"] == len(records)
