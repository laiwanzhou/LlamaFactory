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
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

import pdfplumber
from pypdf import PdfReader

from ..contracts import OwnedBlock, PageEvidence, RuleCandidate, SourceFragment, load_schema, write_jsonl
from ..hashing import sha256_bytes
from ..normalization import normalize_rule_text, parse_level

EXTRACTION_VERSION = "1.0.0"
FINGERPRINT_VERSION = "1.0.0"
SEMANTIC_FIELDS = (
    "class1",
    "class2",
    "class2_definition",
    "class3",
    "class3_definition",
    "class4",
    "class4_description",
    "minimum_security_level",
    "note",
)
LOGICAL_FIELDS = (
    "class1",
    "class2",
    "class2_definition",
    "class3",
    "class3_definition",
    "class4",
    "class4_description",
    "minimum_security_level",
    "note",
)
RELATIVE_BOUNDARIES = (0.0, 0.052, 0.104, 0.195, 0.252, 0.37, 0.475, 0.89, 0.955, 1.001)


class SourcePageRangeError(ValueError):
    pass


class RuntimeDependencyError(RuntimeError):
    pass


class PageRenderer(Protocol):
    version: str

    def render(self, pdf_path: Path, physical_page: int, output_path: Path) -> None: ...


class PopplerPageRenderer:
    def __init__(self, executable: Path):
        self.executable = executable
        probe = subprocess.run([str(executable), "-v"], capture_output=True, text=True, check=False)
        self.version = (probe.stderr or probe.stdout).strip().splitlines()[0]

    @classmethod
    def from_environment(cls) -> PopplerPageRenderer:
        configured = shutil.which("pdftoppm.exe") or shutil.which("pdftoppm")
        if configured is None:
            raise RuntimeDependencyError("pdftoppm is unavailable")
        executable = Path(configured)
        if executable.suffix.casefold() == ".cmd":
            native = executable.parents[2] / "native" / "poppler" / "Library" / "bin" / "pdftoppm.exe"
            if native.is_file():
                executable = native
        return cls(executable)

    def render(self, pdf_path: Path, physical_page: int, output_path: Path) -> None:
        stem = output_path.with_suffix("")
        result = subprocess.run(
            [
                str(self.executable),
                "-f",
                str(physical_page),
                "-l",
                str(physical_page),
                "-singlefile",
                "-png",
                "-r",
                "144",
                str(pdf_path),
                str(stem),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode or not output_path.is_file():
            raise RuntimeDependencyError(result.stderr.strip() or f"failed to render physical page {physical_page}")


@dataclass(frozen=True)
class PageEvidenceSummary:
    page_count: int
    ownership_block_count: int
    unassigned_block_count: int
    page_evidence_jsonl_sha256: str
    page_png_set_sha256: str


def _table_has_a1_header(rows: list[list[str | None]]) -> bool:
    header = " ".join(cell or "" for row in rows[:3] for cell in row)
    return "最低安全" in header or ("四级子类" in header and "内容" in header)


def _logical_field(table_bbox: tuple[float, float, float, float], cell_bbox: tuple[float, float, float, float]) -> str:
    left, _, right, _ = table_bbox
    center = ((cell_bbox[0] + cell_bbox[2]) / 2 - left) / (right - left)
    for index, (start, end) in enumerate(zip(RELATIVE_BOUNDARIES, RELATIVE_BOUNDARIES[1:])):
        if start <= center < end:
            return LOGICAL_FIELDS[index]
    return "unassigned"


def _extract_table_cells(
    page: pdfplumber.page.Page, physical_page: int
) -> tuple[list[dict[str, object]], list[float] | None]:
    candidates = []
    for table_index, table in enumerate(page.find_tables()):
        extracted = table.extract()
        if _table_has_a1_header(extracted):
            candidates.append((table_index, table, extracted))
    if len(candidates) != 1:
        return [], None
    table_index, table, rows = candidates[0]
    raw_cells: list[dict[str, object]] = []
    header_indices = [
        row_index
        for row_index, row in enumerate(rows)
        if any(token in " ".join(cell or "" for cell in row) for token in ("数据归类", "一级", "级别参考"))
    ]
    first_body_row = max(header_indices, default=-1) + 1
    for row_index, (row, row_geometry) in enumerate(zip(rows, table.rows)):
        for column_index, (text, bbox) in enumerate(zip(row, row_geometry.cells)):
            if not text or bbox is None:
                continue
            field_name = _logical_field(table.bbox, bbox)
            ownership = (
                "table_header" if row_index < first_body_row else ("note" if field_name == "note" else "rule_content")
            )
            raw_cells.append(
                {
                    "physical_page": physical_page,
                    "table_index": table_index,
                    "row_index": row_index,
                    "column_index": column_index,
                    "row_locator": f"table_{table_index}:row_{row_index}",
                    "logical_field": field_name,
                    "text": text,
                    "bounding_box": [round(number, 6) for number in bbox],
                    "ownership": ownership,
                    "in_table_body": row_index >= first_body_row,
                }
            )
    return raw_cells, [round(number, 6) for number in table.bbox]


def _extract_blocks(
    page: pdfplumber.page.Page,
    physical_page: int,
    raw_cells: list[dict[str, object]],
    table_bounds: list[float] | None,
) -> list[OwnedBlock]:
    blocks = [
        OwnedBlock(
            block_id=f"p{physical_page:03d}-cell-{index:04d}",
            text=str(cell["text"]),
            bounding_box=list(cell["bounding_box"]),
            ownership=str(cell["ownership"]),
            in_table_body=bool(cell["in_table_body"]),
            row_locator=str(cell["row_locator"]),
        )
        for index, cell in enumerate(raw_cells, 1)
    ]
    if table_bounds is None:
        return blocks
    left, top, right, bottom = table_bounds
    for index, word in enumerate(page.extract_words(x_tolerance=1, y_tolerance=2), 1):
        inside = left <= word["x0"] <= right and top <= word["top"] <= bottom
        if inside:
            continue
        text = word["text"]
        if word["top"] > page.height - 80:
            ownership = "page_footer"
        elif "表A.1" in text or "数据定级规则参考表" in text:
            ownership = "table_header"
        else:
            ownership = "explicitly_ignored"
        blocks.append(
            OwnedBlock(
                block_id=f"p{physical_page:03d}-word-{index:04d}",
                text=text,
                bounding_box=[round(word[key], 6) for key in ("x0", "top", "x1", "bottom")],
                ownership=ownership,
                in_table_body=False,
            )
        )
    return blocks


def extract_page_evidence(
    pdf_path: Path,
    page_start: int = 17,
    page_end: int = 51,
    renderer: PageRenderer | None = None,
) -> list[PageEvidence]:
    reader = PdfReader(pdf_path)
    if page_start < 1 or page_end < page_start or len(reader.pages) < page_end:
        raise SourcePageRangeError(f"required physical pages {page_start}-{page_end}, found {len(reader.pages)}")
    renderer = renderer or PopplerPageRenderer.from_environment()
    pages: list[PageEvidence] = []
    with tempfile.TemporaryDirectory(prefix="jrt0197-render-") as temporary, pdfplumber.open(pdf_path) as pdf:
        for physical_page in range(page_start, page_end + 1):
            page = pdf.pages[physical_page - 1]
            png_path = Path(temporary) / f"physical-page-{physical_page:03d}.png"
            renderer.render(pdf_path, physical_page, png_path)
            png = png_path.read_bytes()
            raw_cells, table_bounds = _extract_table_cells(page, physical_page)
            raw_payload = json.dumps(raw_cells, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            blocks = _extract_blocks(page, physical_page, raw_cells, table_bounds)
            pages.append(
                PageEvidence(
                    physical_page=physical_page,
                    width=page.width,
                    height=page.height,
                    page_png_sha256=sha256_bytes(png),
                    table_bounds=table_bounds,
                    raw_cells=raw_cells,
                    raw_cells_sha256=sha256_bytes(raw_payload),
                    cell_bounding_boxes=[list(cell["bounding_box"]) for cell in raw_cells],
                    blocks=blocks,
                    unassigned_count=sum(block.ownership == "unassigned" for block in blocks),
                    page_png_source=f"physical-page-{physical_page:03d}.png",
                    page_png_bytes=png,
                )
            )
    return pages


def classify_blocks(page: PageEvidence) -> list[OwnedBlock]:
    return page.blocks


def write_page_evidence(pages: Sequence[PageEvidence], evidence_dir: Path) -> PageEvidenceSummary:
    pages_dir = evidence_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for page in pages:
        (pages_dir / f"physical-page-{page.physical_page:03d}.png").write_bytes(page.page_png_bytes)
    evidence_hash = write_jsonl(
        evidence_dir / "jrt0197_page_evidence.jsonl",
        [page.to_mapping() for page in pages],
        load_schema("page-evidence-1.0.0"),
    )
    ordered_pngs = [[page.physical_page, page.page_png_sha256] for page in pages]
    set_hash = sha256_bytes(json.dumps(ordered_pngs, separators=(",", ":")).encode("utf-8"))
    return PageEvidenceSummary(
        page_count=len(pages),
        ownership_block_count=sum(len(page.blocks) for page in pages),
        unassigned_block_count=sum(page.unassigned_count for page in pages),
        page_evidence_jsonl_sha256=evidence_hash,
        page_png_set_sha256=set_hash,
    )


def calculate_rule_semantic_fingerprint(rule: RuleCandidate) -> str:
    value = {name: getattr(rule, name) for name in SEMANTIC_FIELDS}
    payload = json.dumps(value, ensure_ascii=False, sort_keys=False, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def _fragment_for_row(page: PageEvidence, row_locator: str) -> SourceFragment:
    cells = [cell for cell in page.raw_cells if cell["row_locator"] == row_locator]
    boxes = [list(cell["bounding_box"]) for cell in cells]
    block_ids = [block.block_id for block in page.blocks if block.row_locator == row_locator]
    raw_hash = sha256_bytes(
        json.dumps(cells, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return SourceFragment(page.physical_page, row_locator, boxes, block_ids, raw_hash)


def assemble_candidates(pages: Sequence[PageEvidence], run_id: str) -> list[RuleCandidate]:
    del run_id
    mutable: list[dict[str, object]] = []
    inherited: dict[str, tuple[str, int, str]] = {}
    inheritance_fields = LOGICAL_FIELDS[:5]
    for page in pages:
        locators = list(dict.fromkeys(str(cell["row_locator"]) for cell in page.raw_cells if cell["in_table_body"]))
        for locator in locators:
            row_cells = [cell for cell in page.raw_cells if cell["row_locator"] == locator]
            raw = {
                str(cell["logical_field"]): str(cell["text"])
                for cell in row_cells
                if cell["logical_field"] != "unassigned"
            }
            parsed = parse_level(raw.get("minimum_security_level"))
            if (
                parsed.value is None
                and "class4" not in raw
                and mutable
                and any(
                    raw.get(key) for key in ("class4_description", "note", "class2_definition", "class3_definition")
                )
            ):
                previous = mutable[-1]
                for key in ("class4_description", "note", "class2_definition", "class3_definition"):
                    if raw.get(key):
                        previous_raw = previous["raw_extraction"]
                        assert isinstance(previous_raw, dict)
                        previous_raw[key] = "\n".join(filter(None, [str(previous_raw.get(key, "")), raw[key]]))
                fragments = previous["source_fragments"]
                assert isinstance(fragments, list)
                fragments.append(_fragment_for_row(page, locator))
                previous["source_physical_page_end"] = page.physical_page
                continue
            if parsed.value is None and "class4" not in raw:
                continue
            trace: list[dict[str, object]] = []
            if raw.get("class1"):
                inherited.clear()
            elif raw.get("class2"):
                for key in inheritance_fields[2:]:
                    inherited.pop(key, None)
            elif raw.get("class3"):
                for key in inheritance_fields[4:]:
                    inherited.pop(key, None)
            for field_name in inheritance_fields:
                if raw.get(field_name):
                    inherited[field_name] = (raw[field_name], page.physical_page, locator)
                elif field_name in inherited:
                    value, source_page, source_locator = inherited[field_name]
                    raw[field_name] = value
                    trace.append(
                        {
                            "field": field_name,
                            "reason": "collapsed_cell_inheritance",
                            "source_physical_page": source_page,
                            "source_row_locator": source_locator,
                        }
                    )
            fragment = _fragment_for_row(page, locator)
            mutable.append(
                {
                    "source_fragments": [fragment],
                    "source_physical_page_start": page.physical_page,
                    "source_physical_page_end": page.physical_page,
                    "source_physical_page": page.physical_page,
                    "source_row_locator": locator,
                    "raw_extraction": raw,
                    "inheritance_trace": trace,
                    "minimum_security_level_raw": raw.get("minimum_security_level"),
                    "minimum_security_level": parsed.value,
                    "minimum_security_level_parse_status": parsed.status,
                }
            )
    result: list[RuleCandidate] = []
    for source_order, value in enumerate(mutable, 1):
        raw = value["raw_extraction"]
        assert isinstance(raw, dict)
        normalized = {field_name: normalize_rule_text(raw.get(field_name)) for field_name in LOGICAL_FIELDS}
        class4 = normalized["class4"]
        flags = [] if class4 else ["missing_class4_from_source"]
        fragments = value["source_fragments"]
        assert isinstance(fragments, list)
        fragment_payload = json.dumps(
            [fragment.to_mapping() for fragment in fragments],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        candidate = RuleCandidate(
            candidate_id=f"CAND-A1-{source_order:04d}",
            source_order=source_order,
            source_fragments=fragments,
            source_physical_page_start=int(value["source_physical_page_start"]),
            source_physical_page_end=int(value["source_physical_page_end"]),
            source_physical_page=int(value["source_physical_page"]),
            source_row_locator=str(value["source_row_locator"]),
            raw_extraction=raw,
            normalized_content=normalized,
            inheritance_trace=value["inheritance_trace"],
            class1=normalized["class1"],
            class2=normalized["class2"],
            class2_definition=normalized["class2_definition"],
            class3=normalized["class3"],
            class3_definition=normalized["class3_definition"],
            class4=class4,
            class4_description=normalized["class4_description"],
            minimum_security_level=value["minimum_security_level"],
            minimum_security_level_raw=value["minimum_security_level_raw"],
            minimum_security_level_parse_status=str(value["minimum_security_level_parse_status"]),
            note=normalized["note"],
            path_depth=4 if class4 else 3,
            source_structure_status="complete" if class4 else "unconfirmed_missing_class4",
            validation_flags=flags,
            source_fragments_sha256=sha256_bytes(fragment_payload),
            candidate_fingerprint="",
        )
        result.append(replace(candidate, candidate_fingerprint=calculate_rule_semantic_fingerprint(candidate)))
    return result
