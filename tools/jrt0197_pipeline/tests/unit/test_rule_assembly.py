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

from pathlib import Path

from jrt_pipeline.extraction.table_a1 import assemble_candidates, extract_page_evidence

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63606060f80f0001040100a9f6450b0000000049454e44ae426082"
)


class FakeRenderer:
    version = "fake-1"

    def render(self, pdf_path: Path, physical_page: int, output_path: Path) -> None:
        output_path.write_bytes(PNG_1X1)


def test_cross_page_rule_retains_all_fragments(synthetic_pdf: Path) -> None:
    pages = extract_page_evidence(synthetic_pdf, 17, 19, renderer=FakeRenderer())
    candidates = assemble_candidates(pages, "synthetic")
    candidate = candidates[-1]
    assert candidate.class4 == "跨页描述信息"
    assert candidate.class4_description == "描述从本页开始并在下一页继续。"
    assert candidate.source_physical_page_start == 18
    assert candidate.source_physical_page_end == 19
    assert [fragment.physical_page for fragment in candidate.source_fragments] == [18, 19]
    assert candidate.inheritance_trace


def test_candidate_fingerprint_is_stable(synthetic_pdf: Path) -> None:
    pages = extract_page_evidence(synthetic_pdf, 17, 19, renderer=FakeRenderer())
    first = assemble_candidates(pages, "one")
    second = assemble_candidates(pages, "two")
    assert [record.candidate_fingerprint for record in first] == [record.candidate_fingerprint for record in second]
