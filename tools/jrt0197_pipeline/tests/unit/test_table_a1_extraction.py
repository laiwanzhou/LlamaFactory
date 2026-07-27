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

from jrt_pipeline.extraction.table_a1 import extract_page_evidence, write_page_evidence

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63606060f80f0001040100a9f6450b0000000049454e44ae426082"
)


class FakeRenderer:
    version = "fake-1"

    def render(self, pdf_path: Path, physical_page: int, output_path: Path) -> None:
        output_path.write_bytes(PNG_1X1)


def test_extracts_and_persists_scoped_page_evidence(synthetic_pdf: Path, tmp_path: Path) -> None:
    pages = extract_page_evidence(synthetic_pdf, 17, 19, renderer=FakeRenderer())
    assert [page.physical_page for page in pages] == [17, 18, 19]
    assert all(page.page_png_sha256.startswith("sha256:") for page in pages)
    assert {block.ownership for page in pages for block in page.blocks} <= {
        "table_header",
        "rule_content",
        "page_footer",
        "note",
        "explicitly_ignored",
        "unassigned",
    }
    summary = write_page_evidence(pages, tmp_path / "evidence")
    assert summary.page_count == 3
    assert summary.unassigned_block_count == 0
    assert sorted(path.name for path in (tmp_path / "evidence" / "pages").glob("*.png")) == [
        "physical-page-017.png",
        "physical-page-018.png",
        "physical-page-019.png",
    ]
