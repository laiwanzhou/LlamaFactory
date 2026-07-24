# JR/T 0197 Table A.1 Reproducible Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify an auditable JR/T 0197—2020 Table A.1 pipeline whose full lifecycle works on synthetic fixtures, while the only permitted real-data run ends with an immutable `awaiting_review` candidate snapshot.

**Architecture:** A Python CLI owns extraction semantics, canonical contracts, validation, approval, freezing, field mapping, SFT generation, constrained splitting, and audit. A separately invoked JavaScript renderer consumes immutable Python contracts and creates the review workbook without making semantic decisions. Every artifact family is published atomically under a configured external runtime root and carries a named, versioned manifest with deterministic hashes.

**Tech Stack:** Python 3.11–3.13, `pdfplumber==0.11.9`, `pypdf==6.10.0`, `openpyxl==3.1.5`, `jsonschema==4.23.0`, `PyYAML==6.0.1`, `reportlab==4.4.9` for synthetic fixtures, pytest, Ruff 0.13.2, Node.js 24.14.0, and the bundled `@oai/artifact-tool==2.8.24` workbook runtime.

## Global Constraints

- The approved design at `docs/jrt0197_pipeline/2026-07-23-jrt0197-pipeline-design.md` is normative.
- Table A.1, physical PDF pages 17–51 inclusive, is the only semantic truth source; extract and train levels 1–4 only. Level 5 is not extracted, trained, evaluated, or used to manufacture rejection samples, and PDF prose outside Table A.1 cannot supply truth.
- Python is the only semantic and approval authority. JavaScript may render data but may not normalize, classify, validate levels, fingerprint, approve, or allocate IDs.
- Real source files and all runtime artifacts remain outside the repository under an explicit `--runtime-root`; never use LLaMA Factory's repository `data/` directory.
- Real source files, historical audit scripts, templates, and historical result workbooks are read-only.
- The real-data run in this plan is limited to `extract → validate → build-review → awaiting_review`. Never execute real-data `freeze`, field mapping, SFT generation, splitting, or dataset audit.
- Candidate snapshots, frozen versions, and dataset versions are immutable. Existing targets fail and no overwrite flag is implemented.
- Publish from a sibling temporary directory on the same volume only after hashes and validation pass, then rename atomically.
- Core JSON/JSONL output is deterministic UTF-8 with LF, stable key order, compact separators, `ensure_ascii=False`, and a trailing LF. Time and host metadata live only in `run_metadata.json` unless `SOURCE_DATE_EPOCH` is supplied.
- All Python and JavaScript source files use the repository copyright header and LF endings.
- The root repository's test and style behavior must remain unchanged; focused pipeline checks are added explicitly.
- All downstream commands require a valid frozen manifest and master hash. Candidate data is never accepted as training truth.
- All implementation tasks use red-green-refactor and end in a focused commit. Do not combine commits across task boundaries.

---

## File Map

Create the implementation under `tools/jrt0197_pipeline/`:

```text
pipeline.py                         thin executable entry point
pyproject.toml                      isolated Python package and dependency declaration
uv.lock                             resolved Python dependency lock
runtime-lock.json                   externally supplied Node/workbook/runtime versions
package.json / package-lock.json    workbook test scripts and reproducible npm metadata
.gitignore                          runtime and real-data exclusions with fixture allow-list
src/jrt_pipeline/
  cli.py                            command parsing and orchestration
  contracts.py                      typed records, schema loading, deterministic I/O
  hashing.py                        file, semantic, evidence, and set hashing
  normalization.py                  format-only normalization and level parsing
  runtime.py                        external runtime probing and immutable publication
  extraction/table_a1.py            PDF rendering, cell/block extraction, row assembly
  validation/rules.py               candidate validation, severity, and baseline diff
  review/contract.py                review contract export/import and immutability checks
  freeze/service.py                 review application, permanent IDs, frozen publication
  fields/parsers.py                 source-schema-specific CSV/XLSX parsers
  fields/mapping.py                 candidate enumeration and deterministic evidence
  fields/quality_tiers.py           A/B/C/D decisions and truth-field gate
  splitting/constrained.py          deterministic grouped constrained splitter
  sft/common.py                     Alpaca rows, indexes, duplicate/conflict handling
  sft/rules.py                      three rule-task generators
  sft/fields.py                     Chinese, English, supplemental, review entry points
  audit/report.py                   artifact, leakage, coverage, and forbidden-output audit
tools/build_review.mjs              workbook-only renderer
schemas/*.schema.json               versioned contracts
tests/fixtures/                     synthetic PDF/CSV/XLSX/contracts only
tests/unit/                          focused domain tests
tests/integration/                   command and synthetic lifecycle tests
```

Modify repository integration files only where specified below:

```text
.gitignore
Makefile
.github/workflows/tests.yml
```

The artifact filenames are fixed:

```text
candidate/<run_id>/
  jrt0197_rule_master_candidate.jsonl
  jrt0197_rule_candidate_manifest.json
  jrt0197_rule_validation_report.json
  jrt0197_rule_diff.json
  jrt0197_rule_review.xlsx
  evidence/
    jrt0197_page_evidence.jsonl
    pages/
      physical-page-017.png
      physical-page-051.png
  lineage/
    extracted_manifest.json
    validated_manifest.json
  previews/
    workbook/
  run_metadata.json

frozen/<version>/
  jrt0197_rule_master.jsonl
  jrt0197_rule_id_map.json
  jrt0197_rule_manifest.json
  jrt0197_rule_master.sha256

datasets/<version>/
  jrt0197_rule_sft_train.jsonl
  jrt0197_rule_sft_validation.jsonl
  jrt0197_rule_sft_test.jsonl
  finance_field_master.jsonl
  finance_field_review_queue.jsonl
  finance_field_verified_train.jsonl
  finance_field_verified_validation.jsonl
  finance_field_verified_test.jsonl
  finance_field_train_supplemental.jsonl
  finance_field_english_train.jsonl
  finance_field_english_validation.jsonl
  finance_field_english_test.jsonl
  finance_field_english_supplemental.jsonl
```

Every Alpaca JSONL above has a same-order `<filename-without-.jsonl>.index.jsonl`. English train/validation/test are omitted when their independent-coverage gate fails. Candidate-review generation has a schema and command entry point but emits no training file without approved adjudications.

Shared test helpers are explicit production-independent factories under `tools/jrt0197_pipeline/tests/support/`; tests may not define private substitutes with conflicting shapes. A single synthetic source file, `tests/fixtures/contracts/test-records.json`, stores named valid mappings. Task 2 implements the common loader exactly as follows:

```python
FIXTURE_RECORDS = Path(__file__).parents[1] / "fixtures" / "contracts" / "test-records.json"
T = TypeVar("T")


def fixture_value(name: str) -> object:
    payload = json.loads(FIXTURE_RECORDS.read_text(encoding="utf-8"))
    return copy.deepcopy(payload[name])


def fixture_mapping(name: str) -> dict[str, object]:
    value = fixture_value(name)
    if not isinstance(value, dict):
        raise TypeError(f"fixture {name!r} is not an object")
    return value


def make_contract(cls: type[T], name: str, **overrides: object) -> T:
    value = fixture_mapping(name)
    value.update(overrides)
    return cls.from_mapping(value)


def object_schema(key_order: Sequence[str]) -> dict[str, object]:
    return {
        "type": "object",
        "x-key-order": list(key_order),
        "properties": {key: {} for key in key_order},
        "required": list(key_order),
        "additionalProperties": False,
    }
```

The remaining helper ownership and exact public signatures are fixed below; each owning task's Step 3 supplies the body using `make_contract`, a fixture builder, or the real public CLI/service under test:

| Owning task | File | Public helper signatures |
| --- | --- | --- |
| 3–4 | `tests/support/pdf.py` | `build_table_a1_pdf(path: Path, rules: Sequence[SyntheticPdfRule]) -> Path`; `page_evidence_fixture() -> list[PageEvidence]` |
| 5 | `tests/support/rules.py` | `candidate(**overrides: object) -> RuleCandidate`; `complete_evidence() -> list[PageEvidence]`; `manifest(**overrides: object) -> CandidateManifest`; `seed_candidate_and_frozen(runtime_root: Path) -> None`; `current_records() -> list[RuleCandidate]` |
| 6, 8 | `tests/support/reviews.py` | `edit_cell(workbook: Path, sheet: str, column: str, value: object, row: int = 2) -> None`; `approval(**overrides: object) -> WholeRunApproval`; `approved_review(**overrides: object) -> ReviewedCandidateSet`; `prior_frozen() -> SyntheticFrozenVersion`; `corrected_review() -> ReviewedCandidateSet`; `split_review() -> ReviewedCandidateSet` |
| 7 | `tests/support/cli.py` | `cli_runner(*args: str \| Path) -> CliResult`; `core_artifact_hashes(candidate_dir: Path) -> dict[str, str]` |
| 9–10, 13 | `tests/support/fields.py` | `bad_sheet_config() -> SheetConfig`; `field(column_zh_name: str, *, table: str \| None = None, **overrides: object) -> SourceFieldRecord`; `unique_matches() -> list[CandidateMatch]`; `passing_check() -> SemanticCheck`; `decision_for(status: str) -> MappingDecision`; `verified_field(**overrides: object) -> SourceFieldRecord` |
| 11 | `tests/support/splitting.py` | `sample(**overrides: object) -> SplitSample`; `config(**overrides: object) -> SplitConfig`; `group_intersections(result: SplitResult) -> dict[str, list[str]]` |
| 12 | `tests/support/sft.py` | `conflicting_samples() -> list[IndexedSample]`; `same_supervision_from_two_sources() -> list[IndexedSample]` |
| 14 | `tests/support/lifecycle.py` | `SyntheticProject.candidate/approve/freeze/generate_field_master/generate_rule_sft/generate_field_sft/audit`; `inject_group_overlap(dataset_version: SyntheticDatasetVersion) -> None` |

`tests/conftest.py` exposes fixtures by calling only these factories: `synthetic_pdf`, `page_evidence`, `runtime_root`, `validated_dir`, `candidate_dir`, `review_workbook`, `approved_review`, `prior_frozen`, `corrected_review`, `split_review`, `finance_csv`, `train_workbook`, `frozen_rule`, `verified_field`, `samples`, `dataset_version`, and `synthetic_project`. Factory defaults are fixed in `test-records.json`, and every override is explicit, so independently implemented tests share compatible records.

## Task 1: Package Skeleton, Reproducible Runtime, and Repository Integration

**Files:**
- Create: `tools/jrt0197_pipeline/pyproject.toml`
- Create: `tools/jrt0197_pipeline/runtime-lock.json`
- Create: `tools/jrt0197_pipeline/package.json`
- Create: `tools/jrt0197_pipeline/package-lock.json`
- Create: `tools/jrt0197_pipeline/.gitignore`
- Create: `tools/jrt0197_pipeline/pipeline.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/__init__.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/cli.py`
- Create: `tools/jrt0197_pipeline/tests/unit/test_cli.py`
- Modify: `.gitignore`
- Modify: `Makefile`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Produces: `jrt_pipeline.cli.main(argv: Sequence[str] | None = None) -> int`.
- Produces: focused commands `make jrt-quality`, `make jrt-license`, and `make jrt-test-python`.
- Runtime lock fields are exactly `python`, `node`, `artifact_tool`, `pdfplumber`, `pypdf`, `openpyxl`, `jsonschema`, `pyyaml`, and `normalization_version`.

- [ ] **Step 1: Write the failing CLI smoke test**

```python
from jrt_pipeline.cli import build_parser


def test_cli_exposes_approved_commands() -> None:
    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    assert set(choices) == {
        "extract", "validate", "build-review", "freeze", "generate-rule-sft",
        "generate-field-master", "generate-field-sft", "audit", "candidate",
    }
```

- [ ] **Step 2: Run the test and confirm the package is absent**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_cli.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'jrt_pipeline'`.

- [ ] **Step 3: Add the isolated package and thin CLI**

Use `requires-python = ">=3.11,<3.14"`, Hatchling, a `src` package, and the exact dependency versions in the plan header. Put test-only `pytest==7.4.4`, `reportlab==4.4.9`, and `ruff==0.13.2` in a `dev` dependency group. Generate `uv.lock` with `uv lock --project tools/jrt0197_pipeline` and allow only that lock through the root `uv.lock` ignore rule.

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jrt0197-pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "extract", "validate", "build-review", "freeze", "generate-rule-sft",
        "generate-field-master", "generate-field-sft", "audit", "candidate",
    ):
        commands.add_parser(name)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
```

`runtime-lock.json` pins Node `24.14.0` and `@oai/artifact-tool` `2.8.24`; `package.json` has no dependency on the private workbook package. The Python launcher will later resolve its loader-provided module root through configuration and verify the pinned package version before invoking Node.

Add Make targets that run Ruff, the root license checker, and pytest only on `tools/jrt0197_pipeline`. In CI, install the subproject and invoke those targets; do not require the private workbook runtime in public CI.

- [ ] **Step 4: Generate locks and run focused checks**

Run:

```powershell
uv lock --project tools/jrt0197_pipeline
npm --prefix tools/jrt0197_pipeline install --package-lock-only
uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_cli.py
make jrt-quality
make jrt-license
```

Expected: one test passes; Ruff and license checks exit 0; both lock files are tracked.

- [ ] **Step 5: Commit**

```powershell
git add .gitignore Makefile .github/workflows/tests.yml tools/jrt0197_pipeline
git commit -m "build: scaffold JR/T 0197 pipeline"
```

## Task 2: Canonical Contracts, Hashing, and Deterministic Publication

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/contracts.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/hashing.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/runtime.py`
- Create: `tools/jrt0197_pipeline/schemas/rule-candidate-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/schemas/candidate-manifest-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/tests/unit/test_contracts.py`
- Create: `tools/jrt0197_pipeline/tests/unit/test_runtime.py`
- Create: `tools/jrt0197_pipeline/tests/support/__init__.py`
- Create: `tools/jrt0197_pipeline/tests/support/contracts.py`
- Create: `tools/jrt0197_pipeline/tests/fixtures/contracts/test-records.json`
- Create: `tools/jrt0197_pipeline/tests/conftest.py`

**Interfaces:**
- Produces: `write_json(path: Path, value: Mapping[str, object], schema: Mapping[str, object]) -> str` returning `sha256:<hex>`.
- Produces: `write_jsonl(path: Path, records: Iterable[Mapping[str, object]], schema: Mapping[str, object]) -> str`.
- Produces: `read_json(path: Path, schema: Mapping[str, object] | None = None) -> dict[str, object]` and `read_jsonl(path: Path, schema: Mapping[str, object] | None = None) -> list[dict[str, object]]`.
- Produces: `load_schema(schema_name: str) -> dict[str, object]`, `sha256_bytes(payload: bytes) -> str`, and `file_sha256(path: Path) -> str`.
- Produces: `canonicalize_by_schema(value: object, schema: Mapping[str, object]) -> object`, preserving each schema's declared `x-key-order` recursively.
- Produces: `validate_schema(value: object, schema_name: str) -> None`.
- Produces: `atomic_artifact_dir(target: Path) -> ContextManager[Path]` that fails if `target` exists or crosses volumes.
- Produces: `verify_named_manifest(path: Path, expected_schema: str) -> dict[str, object]`.

- [ ] **Step 1: Write failing determinism and publication tests**

```python
def test_jsonl_is_byte_deterministic(tmp_path: Path) -> None:
    left, right = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    records = [{"文本": "客户", "level": 3, "note": None}]
    schema = object_schema(key_order=["文本", "level", "note"])
    assert write_jsonl(left, records, schema) == write_jsonl(right, records, schema)
    assert left.read_bytes() == right.read_bytes()
    assert left.read_bytes().endswith(b"\n")


def test_schema_key_order_is_preserved_in_bytes() -> None:
    schema = object_schema(key_order=["instruction", "input", "output"])
    value = {"output": "o", "input": "i", "instruction": "x"}
    assert canonical_json_bytes(value, schema) == b'{"instruction":"x","input":"i","output":"o"}\n'


def test_atomic_artifact_dir_rejects_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "candidate" / "run-1"
    target.mkdir(parents=True)
    with pytest.raises(ArtifactExistsError):
        with atomic_artifact_dir(target):
            pass
```

- [ ] **Step 2: Confirm both tests fail for missing interfaces**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_contracts.py tools/jrt0197_pipeline/tests/unit/test_runtime.py`

Expected: import errors name the missing deterministic writer and publication context manager.

- [ ] **Step 3: Implement canonical serialization and atomic publication**

```python
def canonicalize_by_schema(value: object, schema: Mapping[str, object]) -> object:
    if isinstance(value, Mapping):
        order = tuple(schema["x-key-order"])
        unknown = set(value) - set(order)
        if unknown:
            raise ContractOrderError(sorted(unknown))
        properties = schema["properties"]
        return {
            key: canonicalize_by_schema(value[key], properties[key])
            for key in order
            if key in value
        }
    if isinstance(value, list):
        return [canonicalize_by_schema(item, schema["items"]) for item in value]
    return value


def canonical_json_bytes(value: object, schema: Mapping[str, object]) -> bytes:
    ordered = canonicalize_by_schema(value, schema)
    text = json.dumps(ordered, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def write_jsonl(path: Path, records: Iterable[Mapping[str, object]], schema: Mapping[str, object]) -> str:
    payload = b"".join(canonical_json_bytes(record, schema) for record in records)
    path.write_bytes(payload)
    return sha256_bytes(payload)


@contextmanager
def atomic_artifact_dir(target: Path) -> Iterator[Path]:
    if target.exists():
        raise ArtifactExistsError(str(target))
    temp = target.parent / f".tmp-{target.name}"
    if temp.exists():
        raise ArtifactExistsError(str(temp))
    temp.mkdir(parents=True)
    try:
        yield temp
        if temp.drive.casefold() != target.drive.casefold():
            raise CrossVolumePublishError(str(target))
        temp.replace(target)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
```

Every object schema declares an explicit `x-key-order`; schema validation rejects undeclared keys. The Alpaca order is `instruction`, `input`, `output`; the SFT index order is the order listed in Task 12; semantic fingerprinting uses `SEMANTIC_FIELDS`, not a schema's alphabetic order. Implement `fixture_mapping`, `make_contract`, and `object_schema` exactly as defined in the shared test-support contract above, and make `tests/conftest.py` import those public factories rather than redefining records. Every contract dataclass implements `from_mapping(cls, value)` and `to_mapping(self)` using its schema order. Define frozen dataclasses for `SourceFragment`, `RuleCandidate`, and `CandidateManifest`, and validate their serialized forms with Draft 2020-12 JSON Schema. Each `SourceFragment` contains physical page, row locator, exact bounding boxes, referenced page-evidence block IDs, and raw-cell hashes. `RuleCandidate` includes `candidate_id`, `source_order`, `source_fragments`, `source_physical_page_start`, `source_physical_page_end`, `source_physical_page`, `raw_extraction`, `inheritance_trace`, and the semantic fields; full page raw cells and cell boxes remain in the persisted evidence JSONL and are replayable through the fragment references. `CandidateManifest` includes `source_pdf_sha256`, `candidate_jsonl_sha256`, `page_evidence_jsonl_sha256`, `page_png_set_sha256`, `page_count`, `ownership_block_count`, `unassigned_block_count`, contract/tool versions, page range, computed record count, comparison baseline, validation state, and pipeline state. Keep `generated_at` out of core manifests; write it only through `write_run_metadata()`.

- [ ] **Step 4: Run unit tests twice and compare bytes**

Run the following command twice:

`uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_contracts.py tools/jrt0197_pipeline/tests/unit/test_runtime.py`

Expected: both runs pass and recorded hashes are identical.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline tools/jrt0197_pipeline/schemas tools/jrt0197_pipeline/tests
git commit -m "feat: add deterministic artifact contracts"
```

## Task 3: PDF Evidence Extraction and Complete Content Ownership

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/extraction/__init__.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/extraction/table_a1.py`
- Create: `tools/jrt0197_pipeline/tests/fixtures/build_table_a1_pdf.py`
- Create: `tools/jrt0197_pipeline/tests/support/pdf.py`
- Modify: `tools/jrt0197_pipeline/tests/fixtures/contracts/test-records.json`
- Modify: `tools/jrt0197_pipeline/tests/conftest.py`
- Create: `tools/jrt0197_pipeline/tests/unit/test_table_a1_extraction.py`

**Interfaces:**
- Defines: `SyntheticPdfRule` with explicit class1–class4, descriptions, level, note, page start/end, and continuation flags for the PDF builder.
- Produces: `extract_page_evidence(pdf_path: Path, page_start: int = 17, page_end: int = 51) -> list[PageEvidence]`.
- Produces: `classify_blocks(page: PageEvidence) -> list[OwnedBlock]` with exactly six ownership classes.
- Produces: `write_page_evidence(pages: Sequence[PageEvidence], evidence_dir: Path) -> PageEvidenceSummary`, writing `jrt0197_page_evidence.jsonl` and page PNGs under `evidence/pages/`.
- `PageEvidence` includes physical page, `page_png_sha256`, table bounds, raw cells, `raw_cells_sha256`, cell boxes, and text blocks.

- [ ] **Step 1: Generate a three-page synthetic continuation fixture and failing test**

The fixture generator creates 16 cover pages and Table A.1 content on physical pages 17–19. Page 18 repeats the header; one rule starts on page 18 and finishes on page 19.

```python
def test_extracts_and_persists_scoped_page_evidence(table_a1_pdf: Path, tmp_path: Path) -> None:
    pages = extract_page_evidence(table_a1_pdf, 17, 19)
    assert [page.physical_page for page in pages] == [17, 18, 19]
    body = [block for page in pages for block in classify_blocks(page) if block.in_table_body]
    assert body
    assert {block.ownership for block in body} <= {
        "table_header", "rule_content", "page_footer", "note", "explicitly_ignored",
    }
    assert all(page.page_png_sha256.startswith("sha256:") for page in pages)
    summary = write_page_evidence(pages, tmp_path / "evidence")
    assert (tmp_path / "evidence" / "jrt0197_page_evidence.jsonl").is_file()
    assert sorted(path.name for path in (tmp_path / "evidence" / "pages").glob("*.png")) == [
        "physical-page-017.png", "physical-page-018.png", "physical-page-019.png",
    ]
    assert summary.page_count == 3
    assert summary.ownership_block_count == sum(len(page.blocks) for page in pages)
```

- [ ] **Step 2: Verify the test fails before extraction exists**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_table_a1_extraction.py`

Expected: import failure for `extract_page_evidence`.

- [ ] **Step 3: Implement coordinate extraction and evidence rendering**

Use `pypdf` only for page-count/range validation and `pdfplumber` for words, lines, tables, and coordinates. Render page PNGs through a configured `pdftoppm` executable; probe `pdftoppm -v`, record its version, and fail with `RuntimeDependencyError` when absent. Synthetic CI tests inject a deterministic fake renderer that writes a known PNG, so public CI does not depend on Poppler.

```python
def extract_page_evidence(
    pdf_path: Path,
    page_start: int = 17,
    page_end: int = 51,
    renderer: PageRenderer | None = None,
) -> list[PageEvidence]:
    reader = PdfReader(pdf_path)
    if len(reader.pages) < page_end:
        raise SourcePageRangeError(page_end)
    renderer = renderer or PopplerPageRenderer.from_environment()
    with pdfplumber.open(pdf_path) as pdf:
        return [
            extract_one_page(pdf.pages[number - 1], number, renderer)
            for number in range(page_start, page_end + 1)
        ]
```

Assign every extracted block before returning. `unassigned` is allowed as evidence output, not silently dropped. `write_page_evidence` serializes raw cells, `cell_bounding_boxes`, table boundaries, text blocks, ownership classification, and page hashes; it names images `physical-page-017.png` through `physical-page-051.png`. Compute `page_png_set_sha256` from canonical ordered pairs `(physical_page, page_png_sha256)`, never filesystem enumeration order, and return the five manifest summary values defined in Task 2.

- [ ] **Step 4: Run extraction tests and inspect the synthetic evidence hashes**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_table_a1_extraction.py -v`

Expected: scoped pages, repeated header recognition, coordinates, ownership, and PNG/raw-cell hashes pass.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/extraction tools/jrt0197_pipeline/tests
git commit -m "feat: extract Table A.1 page evidence"
```

## Task 4: Row Assembly, Normalization, Inheritance, and Candidate Fingerprints

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/normalization.py`
- Modify: `tools/jrt0197_pipeline/src/jrt_pipeline/extraction/table_a1.py`
- Create: `tools/jrt0197_pipeline/tests/unit/test_normalization.py`
- Create: `tools/jrt0197_pipeline/tests/unit/test_rule_assembly.py`

**Interfaces:**
- Produces: `normalize_rule_text(value: str | None) -> str | None`.
- Produces: `parse_level(value: str | int | None) -> ParsedLevel` preserving raw value and status.
- Produces: `assemble_candidates(pages: Sequence[PageEvidence], run_id: str) -> list[RuleCandidate]`.
- Produces: `calculate_rule_semantic_fingerprint(rule: RuleCandidate) -> str` over the exact nine semantic fields in the design. Candidate records store the result as `candidate_fingerprint`; Task 8 stores the recomputed result as `rule_fingerprint` in frozen records.

- [ ] **Step 1: Write failing normalization and cross-page assembly tests**

```python
def test_normalization_changes_layout_not_words() -> None:
    assert normalize_rule_text(" 交易\n 金额，信息 ") == "交易 金额,信息"
    assert normalize_rule_text("疑似错別字") == "疑似错別字"


def test_cross_page_rule_retains_all_fragments(page_evidence: list[PageEvidence]) -> None:
    candidate = assemble_candidates(page_evidence, "run-1")[1]
    assert candidate.source_physical_page_start == 18
    assert candidate.source_physical_page_end == 19
    assert [f.physical_page for f in candidate.source_fragments] == [18, 19]
    assert candidate.inheritance_trace


def test_semantic_fingerprint_uses_declared_field_order() -> None:
    rule = make_contract(RuleCandidate, "rule_candidate")
    ordered = {name: getattr(rule, name) for name in SEMANTIC_FIELDS}
    expected = sha256_bytes(
        json.dumps(ordered, ensure_ascii=False, sort_keys=False, separators=(",", ":")).encode("utf-8")
    )
    assert calculate_rule_semantic_fingerprint(rule) == expected
```

- [ ] **Step 2: Confirm failure for missing normalization and assembler**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_normalization.py tools/jrt0197_pipeline/tests/unit/test_rule_assembly.py`

Expected: missing interface failures.

- [ ] **Step 3: Implement format-only normalization and explicit inheritance**

```python
SEMANTIC_FIELDS = (
    "class1", "class2", "class2_definition", "class3", "class3_definition",
    "class4", "class4_description", "minimum_security_level", "note",
)


def calculate_rule_semantic_fingerprint(rule: RuleCandidate) -> str:
    value = {name: getattr(rule, name) for name in SEMANTIC_FIELDS}
    payload = json.dumps(value, ensure_ascii=False, sort_keys=False, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)
```

Collapsed cells inherit only from an earlier explicit source cell, with `source_fragment_hash`, field name, and reason stored in `inheritance_trace`. Detect missing sources and cycles. Candidate assembly assigns consecutive run-local IDs in source order, beginning with `CAND-A1-0001`, and writes `source_order`, `source_fragments_sha256`, and the semantic result to `candidate_fingerprint`. A missing fourth level emits `path_depth=3`, `source_structure_status="unconfirmed_missing_class4"`, and `validation_flags=["missing_class4_from_source"]`; never synthesize a class name.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_normalization.py tools/jrt0197_pipeline/tests/unit/test_rule_assembly.py -v`

Expected: punctuation/whitespace normalization, raw preservation, level forms, inheritance trace, multi-page fragments, and stable fingerprints pass.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline tools/jrt0197_pipeline/tests/unit
git commit -m "feat: assemble normalized rule candidates"
```

## Task 5: Candidate Validation, Baseline Difference, and Immutable Candidate Publication

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/validation/__init__.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/validation/rules.py`
- Create: `tools/jrt0197_pipeline/schemas/validation-report-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/schemas/rule-diff-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/schemas/extracted-manifest-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/schemas/validated-manifest-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/schemas/frozen-rule-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/schemas/frozen-manifest-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/schemas/rule-id-map-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/tests/unit/test_rule_validation.py`
- Create: `tools/jrt0197_pipeline/tests/integration/test_candidate_publication.py`
- Create: `tools/jrt0197_pipeline/tests/support/rules.py`
- Modify: `tools/jrt0197_pipeline/tests/fixtures/contracts/test-records.json`
- Modify: `tools/jrt0197_pipeline/tests/conftest.py`

**Interfaces:**
- Produces: `validate_candidates(records, evidence, manifest) -> ValidationReport`.
- Produces: `diff_candidates(current, runtime_root) -> RuleDiff` using frozen → prior candidate → no baseline precedence.
- Produces: `publish_extracted_artifact(config: ExtractConfig, output: Path, artifact_id: str) -> Path` with `pipeline_state="extracted"`.
- Produces: `publish_validated_artifact(input_dir: Path, output: Path, artifact_id: str, runtime_root: Path, diagnostic: bool = False) -> Path` with `pipeline_state="validated"` and immutable parent linkage.
- Every validated manifest stores `parent_artifact_id` and `parent_artifact_manifest_sha256`; neither function mutates its input.

- [ ] **Step 1: Write failing severity and baseline tests**

```python
@pytest.mark.parametrize("record,code", [
    (candidate(minimum_security_level=5), "level_out_of_scope"),
    (candidate(class4=None), "missing_class4_from_source"),
])
def test_blocking_rule_findings(record: RuleCandidate, code: str) -> None:
    report = validate_candidates([record], complete_evidence(), manifest())
    assert ("error", code) in {(f.severity, f.code) for f in report.findings}
    assert report.validation_status == "failed"


def test_diff_prefers_latest_frozen_baseline(runtime_root: Path) -> None:
    seed_candidate_and_frozen(runtime_root)
    assert diff_candidates(current_records(), runtime_root).baseline_type == "frozen"
```

- [ ] **Step 2: Verify failures**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_rule_validation.py tools/jrt0197_pipeline/tests/integration/test_candidate_publication.py`

Expected: missing validator/diff failures.

- [ ] **Step 3: Implement all approved findings and named manifests**

```python
ERROR_CODES = {
    "level_out_of_scope", "level_unparseable", "source_page_missing",
    "inheritance_source_missing", "inheritance_cycle", "path_level_conflict",
    "unassigned_table_body", "missing_class4_from_source", "hash_mismatch",
    "schema_invalid",
}


def candidate(**overrides: object) -> RuleCandidate:
    return make_contract(RuleCandidate, "rule_candidate", **overrides)


def complete_evidence() -> list[PageEvidence]:
    return [PageEvidence.from_mapping(value) for value in fixture_value("complete_page_evidence")]


def manifest(**overrides: object) -> CandidateManifest:
    return make_contract(CandidateManifest, "candidate_manifest", **overrides)


def current_records() -> list[RuleCandidate]:
    return [candidate()]


def seed_candidate_and_frozen(runtime_root: Path) -> None:
    candidate_dir = runtime_root / "candidate" / "baseline-candidate"
    candidate_dir.mkdir(parents=True)
    candidate_hash = write_jsonl(
        candidate_dir / "jrt0197_rule_master_candidate.jsonl",
        [candidate().to_mapping()],
        load_schema("rule-candidate-1.0.0"),
    )
    write_json(
        candidate_dir / "jrt0197_rule_candidate_manifest.json",
        manifest(candidate_jsonl_sha256=candidate_hash).to_mapping(),
        load_schema("candidate-manifest-1.0.0"),
    )

    frozen_dir = runtime_root / "frozen" / "1.0.0"
    frozen_dir.mkdir(parents=True)
    frozen_rule = fixture_mapping("frozen_rule")
    master_hash = write_jsonl(
        frozen_dir / "jrt0197_rule_master.jsonl",
        [frozen_rule],
        load_schema("frozen-rule-1.0.0"),
    )
    frozen_manifest = fixture_mapping("frozen_manifest")
    frozen_manifest["master_sha256"] = master_hash
    write_json(
        frozen_dir / "jrt0197_rule_manifest.json",
        frozen_manifest,
        load_schema("frozen-manifest-1.0.0"),
    )
    write_json(
        frozen_dir / "jrt0197_rule_id_map.json",
        fixture_mapping("rule_id_map"),
        load_schema("rule-id-map-1.0.0"),
    )
    (frozen_dir / "jrt0197_rule_master.sha256").write_text(
        f"{master_hash}\n", encoding="utf-8", newline="\n"
    )
```

`seed_candidate_and_frozen(runtime_root)` uses the production deterministic writers and the `rule_candidate`, `candidate_manifest`, `frozen_rule`, and `frozen_manifest` mappings in `test-records.json`; it computes real content hashes before publishing both valid baseline directories. The validator also reports duplicate semantic fingerprints, path discontinuities, missing page/evidence/order data, same class4 under multiple paths, baseline count/distribution changes, and level distributions. Diff baseline order is the latest frozen master, otherwise the latest prior candidate, otherwise `baseline_status="no_baseline"`. Build each manifest only from computed counts and hashes. The extracted artifact persists candidate JSONL plus `evidence/jrt0197_page_evidence.jsonl` and `evidence/pages/*.png`; the validated artifact copies those verified bytes, stores the exact extracted manifest at `lineage/extracted_manifest.json`, adds validation/diff files, and records that manifest hash as its parent. Write diagnostic workbooks only when explicitly requested later, marking them `diagnostic_only` and non-freezable.

- [ ] **Step 4: Run publication tests, then rerun against the same inputs**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_rule_validation.py tools/jrt0197_pipeline/tests/integration/test_candidate_publication.py -v`

Expected: validation status and baseline precedence pass; evidence survives both immutable stages; parent hashes verify; a repeated target fails before any file changes.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/validation tools/jrt0197_pipeline/schemas tools/jrt0197_pipeline/tests
git commit -m "feat: validate and diff candidate rules"
```

## Task 6: JavaScript Review Workbook and Python Review Contract

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/review/__init__.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/review/contract.py`
- Create: `tools/jrt0197_pipeline/tools/build_review.mjs`
- Create: `tools/jrt0197_pipeline/schemas/review-contract-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/tests/unit/test_review_contract.py`
- Create: `tools/jrt0197_pipeline/tests/integration/test_review_workbook.py`
- Create: `tools/jrt0197_pipeline/tests/js/build_review.test.mjs`
- Create: `tools/jrt0197_pipeline/tests/support/reviews.py`
- Modify: `tools/jrt0197_pipeline/tests/conftest.py`

**Interfaces:**
- Produces: `build_review_contract(validated_dir: Path) -> dict[str, object]` from an immutable `pipeline_state="validated"` artifact.
- Produces: `invoke_workbook_builder(contract_path: Path, output_path: Path, preview_dir: Path, runtime: WorkbookRuntime) -> None`.
- JS CLI: `node build_review.mjs --contract <json> --workbook <xlsx> --preview-dir <dir>`.
- Workbook sheets are exactly `审核说明`, `候选规则`, `自动校验问题`, `差异对照`, `统计汇总`, `候选清单`, and hidden/protected `__review_metadata`.
- `preview_dir` must resolve to `<candidate>/previews/workbook`; the builder rejects `<candidate>/evidence`, `<candidate>/evidence/pages`, or the candidate root as a preview destination.

- [ ] **Step 1: Write failing contract and workbook structure tests**

```python
def test_review_contract_contains_only_python_decisions(validated_dir: Path) -> None:
    contract = build_review_contract(validated_dir)
    assert contract["editable_columns"] == [
        "class1", "class2", "class2_definition", "class3", "class3_definition",
        "class4", "class4_description", "minimum_security_level", "note",
        "source_structure_decision", "lineage_decision", "prior_rule_ids", "retained_rule_id",
        "review_decision", "review_comment", "reviewer", "reviewed_at",
    ]
    assert contract["candidate_jsonl_sha256"] == file_sha256(validated_dir / "jrt0197_rule_master_candidate.jsonl")
```

The JS test loads a minimized fixture contract, builds the workbook, and asserts sheet names, metadata values, frozen panes, filters, protected metadata, and review-column styling through `@oai/artifact-tool`.

- [ ] **Step 2: Confirm Python tests fail and workbook test reports missing configured runtime**

Run:

```powershell
uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_review_contract.py
npm --prefix tools/jrt0197_pipeline test
```

Expected: Python import failure; Node test is skipped with an explicit message when `JRT0197_NODE_MODULES` is unset, or fails for missing builder when the bundled runtime is configured.

- [ ] **Step 3: Implement the renderer boundary and runtime probe**

Python writes a fully resolved review JSON contract; JS never recalculates values. `source_structure_decision` allows exactly `not_applicable`, `confirmed_source_has_no_class4`, or `extraction_error_requires_new_candidate`. `lineage_decision` allows exactly `unchanged`, `corrected_existing_rule`, `new_rule`, `split_from`, or `merged_from`; `prior_rule_ids` is a semicolon-separated list rendered as a JSON array on Python import, and `retained_rule_id` is either one prior ID or null. Python prepopulates `unchanged` only for a unique exact fingerprint match and `new_rule` only when no historical candidate matches; ambiguous, split, merge, or corrected cases remain unapproved until the reviewer supplies explicit lineage. These four review fields are approval metadata and never enter `candidate_fingerprint` or `rule_fingerprint`. The Python runtime probe verifies Node and package versions against `runtime-lock.json`, creates a temporary module-resolution junction under the runtime directory when required, invokes Node, and removes the junction afterward. The protected `__review_metadata` sheet stores exactly `run_id`, `candidate_jsonl_sha256`, `manifest_sha256`, `review_schema_version`, `editable_columns`, `candidate_id_count`, and `candidate_id_set_hash`; Python still performs row-by-row immutable comparisons.

```javascript
const SHEETS = ["审核说明", "候选规则", "自动校验问题", "差异对照", "统计汇总", "候选清单"];
const EDITABLE = new Set(contract.editable_columns);

for (const name of SHEETS) workbook.addWorksheet(name);
renderCandidateRows(workbook.getWorksheet("候选规则"), contract.records, EDITABLE);
renderMetadataSheet(workbook, contract.metadata, { hidden: true, protected: true });
await workbook.write(outputPath);
await renderAllSheets(workbook, previewDir);
```

The Python workbook mutation helper used only by negative tests is complete and shared:

```python
def edit_cell(workbook: Path, sheet: str, column: str, value: object, row: int = 2) -> None:
    book = openpyxl.load_workbook(workbook)
    worksheet = book[sheet]
    headers = {cell.value: cell.column for cell in worksheet[1]}
    worksheet.cell(row=row, column=headers[column], value=value)
    book.save(workbook)
```

Apply restrained colors, filters, frozen panes, widths, wrap text, severity highlighting, and visually distinct editable columns. Fail when an approvable build has validation errors. Diagnostic mode watermarks every user-facing sheet.

- [ ] **Step 4: Run contract tests and visually inspect every synthetic preview**

Run:

```powershell
uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_review_contract.py tools/jrt0197_pipeline/tests/integration/test_review_workbook.py
$env:JRT0197_NODE_MODULES='<bundled-node-modules-root>'; npm --prefix tools/jrt0197_pipeline test
```

Expected: tests pass; each expected sheet has a nonblank preview; counts and metadata match the candidate contract; no clipped header, broken formula, or unreadable review column remains.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/review tools/jrt0197_pipeline/tools tools/jrt0197_pipeline/schemas tools/jrt0197_pipeline/tests
git commit -m "feat: build auditable rule review workbook"
```

## Task 7: Unified Candidate CLI Orchestration

**Files:**
- Modify: `tools/jrt0197_pipeline/src/jrt_pipeline/cli.py`
- Modify: `tools/jrt0197_pipeline/pipeline.py`
- Create: `tools/jrt0197_pipeline/tests/integration/test_candidate_cli.py`
- Create: `tools/jrt0197_pipeline/tests/support/cli.py`
- Modify: `tools/jrt0197_pipeline/tests/conftest.py`

**Interfaces:**
- Defines: `CliResult(exit_code: int, stdout: str, stderr: str)` in `tests/support/cli.py`.
- `extract --pdf PATH --output PATH --artifact-id ID [--source-date-epoch INT]` publishes one immutable extracted directory.
- `validate --input PATH --output PATH --artifact-id ID --runtime-root PATH` reads an extracted directory and publishes a different immutable validated directory.
- `build-review --input PATH --output PATH --run-id ID` reads a validated directory and publishes the final immutable candidate directory.
- `candidate --pdf PATH --runtime-root PATH --run-id ID [--source-date-epoch INT]` performs the three stages inside one temporary transaction and publishes only `<runtime_root>/candidate/<run_id>`.
- Produces `jrt0197_rule_candidate_manifest.json` with `pipeline_state="awaiting_review"` only after workbook and previews pass checks.
- Standalone and combined execution are byte-identical for the final core candidate files when they use artifact IDs `<run_id>:extracted` and `<run_id>:validated`, the same run ID/config/runtime versions, and the same `SOURCE_DATE_EPOCH`; only separately stored `run_metadata.json` may differ.

- [ ] **Step 1: Write a failing synthetic candidate command test**

```python
def test_candidate_command_stops_at_awaiting_review(cli_runner, synthetic_pdf, runtime_root) -> None:
    result = cli_runner(
        "candidate", "--pdf", synthetic_pdf, "--runtime-root", runtime_root, "--run-id", "synthetic-001"
    )
    assert result.exit_code == 0
    candidate = runtime_root / "candidate" / "synthetic-001"
    manifest = read_json(candidate / "jrt0197_rule_candidate_manifest.json")
    assert manifest["pipeline_state"] == "awaiting_review"
    assert not (runtime_root / "frozen").exists()
    assert not (runtime_root / "datasets").exists()


def test_standalone_stages_match_combined_candidate(cli_runner, synthetic_pdf, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1784769600")
    extracted, validated = tmp_path / "extracted", tmp_path / "validated"
    standalone, combined_root = tmp_path / "standalone", tmp_path / "combined-root"
    cli_runner("extract", "--pdf", synthetic_pdf, "--output", extracted, "--artifact-id", "same:extracted")
    cli_runner(
        "validate", "--input", extracted, "--output", validated,
        "--artifact-id", "same:validated", "--runtime-root", tmp_path,
    )
    cli_runner("build-review", "--input", validated, "--output", standalone, "--run-id", "same")
    cli_runner("candidate", "--pdf", synthetic_pdf, "--runtime-root", combined_root, "--run-id", "same")
    assert core_artifact_hashes(standalone) == core_artifact_hashes(combined_root / "candidate" / "same")
```

- [ ] **Step 2: Run and confirm the command is not wired**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/integration/test_candidate_cli.py`

Expected: nonzero result because orchestration is absent.

- [ ] **Step 3: Wire extract → validate → build-review in one transaction**

```python
def run_candidate(args: CandidateArgs) -> int:
    target = args.runtime_root / "candidate" / args.run_id
    with atomic_artifact_dir(target) as staging:
        extracted = staging / ".stages" / "extracted"
        validated = staging / ".stages" / "validated"
        extract_to_staging(args.pdf, extracted, artifact_id=f"{args.run_id}:extracted", args=args)
        report = validate_to_staging(
            extracted, validated, artifact_id=f"{args.run_id}:validated", runtime_root=args.runtime_root
        )
        if report.error_count:
            raise CandidateValidationError(report.error_count)
        build_review_in_staging(validated, staging, args)
        shutil.rmtree(staging / ".stages")
        finalize_candidate_manifest(staging, pipeline_state="awaiting_review")
        verify_candidate_artifacts(staging)
    return 0


def cli_runner(*args: str | Path) -> CliResult:
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main([str(arg) for arg in args])
    return CliResult(exit_code=exit_code, stdout=stdout.getvalue(), stderr=stderr.getvalue())


def core_artifact_hashes(candidate_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(candidate_dir).as_posix(): file_sha256(path)
        for path in sorted(candidate_dir.rglob("*"))
        if path.is_file() and path.name != "run_metadata.json"
    }
```

The final manifest stores `parent_artifact_id="<run_id>:validated"` and the validated manifest hash. `build-review` copies the extracted and validated manifests to `lineage/extracted_manifest.json` and `lineage/validated_manifest.json`, copies verified evidence/candidate/validation/diff bytes, writes the workbook to the candidate root, and writes workbook previews only under `previews/workbook/`. Reject repository-relative implicit runtime roots, missing run IDs, out-of-scope page overrides, and existing targets. Emit machine-readable failure codes and leave neither temporary nor partial target directories.

- [ ] **Step 4: Run positive and negative command tests**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/integration/test_candidate_cli.py -v`

Expected: successful synthetic candidate ends at `awaiting_review`; standalone inputs remain unchanged; every child manifest verifies its parent; standalone and combined core hashes match; invalid PDF, validation error, renderer failure, and existing output leave no published snapshot.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/cli.py tools/jrt0197_pipeline/pipeline.py tools/jrt0197_pipeline/tests/integration/test_candidate_cli.py
git commit -m "feat: orchestrate immutable candidate runs"
```

## Task 8: Review Import, Approval Gates, Freeze, and Permanent Rule IDs

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/freeze/__init__.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/freeze/service.py`
- Modify: `tools/jrt0197_pipeline/schemas/frozen-rule-1.0.0.schema.json`
- Modify: `tools/jrt0197_pipeline/schemas/frozen-manifest-1.0.0.schema.json`
- Modify: `tools/jrt0197_pipeline/schemas/rule-id-map-1.0.0.schema.json`
- Modify: `tools/jrt0197_pipeline/src/jrt_pipeline/review/contract.py`
- Modify: `tools/jrt0197_pipeline/src/jrt_pipeline/cli.py`
- Create: `tools/jrt0197_pipeline/tests/unit/test_review_import.py`
- Create: `tools/jrt0197_pipeline/tests/integration/test_freeze.py`
- Modify: `tools/jrt0197_pipeline/tests/support/reviews.py`
- Modify: `tools/jrt0197_pipeline/tests/fixtures/contracts/test-records.json`
- Modify: `tools/jrt0197_pipeline/tests/conftest.py`

**Interfaces:**
- Produces: `import_review(candidate_dir: Path, workbook: Path) -> ReviewedCandidateSet`.
- Produces: `freeze(reviewed: ReviewedCandidateSet, runtime_root: Path, version: str, approval: WholeRunApproval) -> Path`.
- CLI is exactly `freeze --runtime-root PATH --candidate-run-id ID --reviewed-workbook PATH --version VERSION --approved-by NAME --approved-at ISO8601 --approval-note TEXT --approval-scope TEXT`.
- Defines: immutable `FrozenRule` and `FrozenManifest` records validated by the frozen schemas and consumed by Tasks 9–14.
- Defines: test-only `SyntheticFrozenVersion(runtime_root: Path, version: str, id_map: tuple[RuleIdMapEntry, ...])` in `tests/support/reviews.py`.
- Defines: `resolve_rule_lineage(reviewed: ReviewedCandidateSet, prior_map: Sequence[RuleIdMapEntry]) -> list[ResolvedRuleIdentity]`.
- A `RuleIdMapEntry` stores `rule_id`, `current_fingerprint`, ordered unique `historical_fingerprints`, `lineage_status`, `prior_rule_ids`, and `retained_rule_id`.

- [ ] **Step 1: Write failing gates for immutable edits and real-rule rejection**

```python
def test_freeze_rejects_immutable_source_edit(review_workbook, candidate_dir) -> None:
    edit_cell(review_workbook, "候选规则", "source_physical_page_start", 99)
    with pytest.raises(ImmutableReviewCellChanged):
        import_review(candidate_dir, review_workbook)


def test_freeze_blocks_reextract_decision(approved_review) -> None:
    approved_review.records[0].decision = "reject_requires_reextraction"
    with pytest.raises(FreezeApprovalError, match="requires_reextraction"):
        freeze(approved_review, approved_review.runtime_root, "1.0.0", approval())


@pytest.mark.parametrize("decision,allowed", [
    ("confirmed_source_has_no_class4", True),
    ("extraction_error_requires_new_candidate", False),
    (None, False),
])
def test_missing_class4_requires_explicit_structure_decision(approved_review, decision, allowed) -> None:
    approved_review.records[0].candidate.class4 = None
    approved_review.records[0].source_structure_decision = decision
    if allowed:
        frozen_dir = freeze(approved_review, approved_review.runtime_root, "1.0.0", approval())
        assert read_jsonl(frozen_dir / "jrt0197_rule_master.jsonl")[0]["path_depth"] == 3
    else:
        with pytest.raises(FreezeApprovalError):
            freeze(approved_review, approved_review.runtime_root, "1.0.0", approval())


def test_approved_correction_changes_fingerprint_but_keeps_rule_id(prior_frozen, corrected_review) -> None:
    identities = resolve_rule_lineage(corrected_review, prior_frozen.id_map)
    assert identities[0].rule_id == "JRT0197-A1-0001"
    assert identities[0].current_fingerprint != prior_frozen.id_map[0].current_fingerprint
    assert prior_frozen.id_map[0].current_fingerprint in identities[0].historical_fingerprints


def test_ambiguous_or_unmapped_split_blocks_freeze(prior_frozen, split_review) -> None:
    split_review.records[0].retained_rule_id = None
    with pytest.raises(RuleLineageError, match="explicit lineage mapping required"):
        resolve_rule_lineage(split_review, prior_frozen.id_map)


def test_new_rule_uses_tail_id(prior_frozen, approved_review) -> None:
    approved_review.records[0].lineage_decision = "new_rule"
    identity = resolve_rule_lineage(approved_review, prior_frozen.id_map)[0]
    assert identity.rule_id == "JRT0197-A1-0002"


def test_merge_requires_explicit_retained_prior_id(prior_frozen, approved_review) -> None:
    approved_review.records[0].lineage_decision = "merged_from"
    approved_review.records[0].prior_rule_ids = ("JRT0197-A1-0001", "JRT0197-A1-0002")
    approved_review.records[0].retained_rule_id = None
    with pytest.raises(RuleLineageError, match="retained_rule_id"):
        resolve_rule_lineage(approved_review, prior_frozen.id_map)


def test_structure_and_lineage_decisions_do_not_change_semantic_fingerprint(approved_review) -> None:
    before = calculate_rule_semantic_fingerprint(approved_review.records[0].candidate)
    approved_review.records[0].source_structure_decision = "not_applicable"
    approved_review.records[0].lineage_decision = "new_rule"
    after = calculate_rule_semantic_fingerprint(approved_review.records[0].candidate)
    assert after == before
```

- [ ] **Step 2: Run and confirm freeze interfaces are missing**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_review_import.py tools/jrt0197_pipeline/tests/integration/test_freeze.py`

Expected: missing import/freeze failures.

- [ ] **Step 3: Implement the two-layer approval and freeze transaction**

Accept only `approve`, `modify`, `reject_as_extraction_artifact`, `reject_as_duplicate`, and `reject_requires_reextraction`. Require comments for every modify/reject, row reviewer/time for every row, and `approved_by`, `approved_at`, `approval_note`, and `approval_scope` for the run. Compare all immutable cells, `candidate_id_count`, `candidate_id_set_hash`, `manifest_sha256`, and `candidate_jsonl_sha256`. Empty or illegal `source_structure_decision` on a `class4=null` row blocks import; `not_applicable` is required for an ordinary four-level row.

```python
def apply_review(record: RuleCandidate, row: ReviewRow) -> RuleCandidate:
    if row.decision == "approve":
        return record
    if row.decision == "modify":
        proposed = replace(record, **{name: row.proposals[name] for name in EDITABLE_SEMANTIC_FIELDS})
        return normalize_and_fingerprint(proposed)
    if row.decision in {"reject_as_extraction_artifact", "reject_as_duplicate"}:
        return replace(record, freeze_excluded=True, exclusion_reason=row.decision)
    raise FreezeApprovalError(row.decision)


def approval(**overrides: object) -> WholeRunApproval:
    return make_contract(WholeRunApproval, "whole_run_approval", **overrides)


def approved_review(**overrides: object) -> ReviewedCandidateSet:
    return make_contract(ReviewedCandidateSet, "approved_review", **overrides)


def prior_frozen() -> SyntheticFrozenVersion:
    return make_contract(SyntheticFrozenVersion, "prior_frozen")


def corrected_review() -> ReviewedCandidateSet:
    return make_contract(ReviewedCandidateSet, "corrected_review")


def split_review() -> ReviewedCandidateSet:
    return make_contract(ReviewedCandidateSet, "split_review")
```

An unconfirmed missing fourth level can become `confirmed_source_has_no_class4` only through the explicit structure decision; `extraction_error_requires_new_candidate` and `reject_requires_reextraction` both block freeze. Exact unique fingerprints reuse the prior `rule_id` with `lineage_status="unchanged"`. An approved correction requires `lineage_decision="corrected_existing_rule"`, exactly one prior ID, and the same `retained_rule_id`; it retains that ID and moves the prior fingerprint into `historical_fingerprints`. `new_rule` requires no prior IDs and receives the next tail ID. `split_from` requires one prior ID and an explicit retained ID for at most one child; other children receive tail IDs. `merged_from` requires two or more prior IDs and one explicitly retained prior ID. Missing, conflicting, multiply retained, or ambiguous lineage blocks automatic freeze.

The permanent map serializes corrected lineage in this fixed shape:

```json
{
  "rule_id": "JRT0197-A1-0001",
  "current_fingerprint": "sha256:new",
  "historical_fingerprints": ["sha256:old"],
  "lineage_status": "corrected_existing_rule",
  "prior_rule_ids": ["JRT0197-A1-0001"],
  "retained_rule_id": "JRT0197-A1-0001"
}
```

Re-run full validation after review application. Allocate permanent IDs such as `JRT0197-A1-0001`, recompute `rule_fingerprint` from the reviewed normalized semantic fields rather than copying `candidate_fingerprint`, and retain `source_order`. Publish exactly `jrt0197_rule_master.jsonl`, `jrt0197_rule_id_map.json`, `jrt0197_rule_manifest.json`, and `jrt0197_rule_master.sha256` atomically, then verify the checksum file. The named manifest contains `freeze_status="frozen"`, `freeze_version`, approvals, `source_pdf_sha256`, computed `rule_count`, `master_sha256`, extraction/normalization/fingerprint versions, and `validation_status="passed"`. Never edit the candidate directory.

- [ ] **Step 4: Run all freeze tests including ID stability across versions**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_review_import.py tools/jrt0197_pipeline/tests/integration/test_freeze.py -v`

Expected: approved synthetic records freeze; corrected rules retain IDs and fingerprint history; new rules append IDs; explicit split/merge mappings work; ambiguous lineage, multiply retained IDs, rejected real rules, invalid class4 structure decisions, and absent whole-run approval block publication.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/freeze tools/jrt0197_pipeline/src/jrt_pipeline/review tools/jrt0197_pipeline/src/jrt_pipeline/cli.py tools/jrt0197_pipeline/schemas tools/jrt0197_pipeline/tests
git commit -m "feat: freeze reviewed Table A.1 rules"
```

## Task 9: Heterogeneous Field Parsers and Unified Field Master

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/fields/__init__.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/fields/parsers.py`
- Create: `tools/jrt0197_pipeline/schemas/field-master-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/tests/fixtures/field_sources.py`
- Create: `tools/jrt0197_pipeline/tests/unit/test_field_parsers.py`
- Create: `tools/jrt0197_pipeline/tests/support/fields.py`
- Modify: `tools/jrt0197_pipeline/tests/fixtures/contracts/test-records.json`
- Modify: `tools/jrt0197_pipeline/tests/conftest.py`

**Interfaces:**
- Produces: `parse_finance_csv(path: Path, encoding: str = "gb2312") -> list[SourceFieldRecord]`.
- Produces: `parse_train_workbook(path: Path, sheet_configs: Sequence[SheetConfig]) -> list[SourceFieldRecord]`.
- Produces: `parse_sources(sources: Sequence[SourceConfig]) -> list[SourceFieldRecord]` for Task 10 to map and publish.
- `SourceFieldRecord` preserves raw/normalized names and paths plus `provided_level_raw`, parsed value, and parse status.

- [ ] **Step 1: Write failing source-specific parser tests**

```python
def test_gb2312_csv_preserves_raw_and_parsed_level(finance_csv: Path) -> None:
    record = parse_finance_csv(finance_csv)[0]
    assert record.source_schema == "finance_result_csv_v1"
    assert record.provided_level_raw == "三级"
    assert record.provided_level_parsed == 3
    assert record.provided_level_parse_status == "parsed"


def test_workbook_requires_configured_columns(train_workbook: Path) -> None:
    with pytest.raises(SourceSchemaError, match="字段中文名"):
        parse_train_workbook(train_workbook, [bad_sheet_config()])
```

- [ ] **Step 2: Verify source parsers are absent**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_field_parsers.py`

Expected: missing parser failures.

- [ ] **Step 3: Implement explicit schema parsing and master publication**

```python
PARSERS: dict[str, Callable[[SourceConfig], list[SourceFieldRecord]]] = {
    "finance_result_csv_v1": parse_finance_csv_config,
    "train_data_workbook_v1": parse_train_workbook_config,
}


def parse_source(config: SourceConfig) -> list[SourceFieldRecord]:
    try:
        parser = PARSERS[config.source_schema]
    except KeyError as exc:
        raise SourceSchemaError(config.source_schema) from exc
    return parser(config)


def bad_sheet_config() -> SheetConfig:
    return make_contract(SheetConfig, "bad_sheet_config")
```

Do not infer columns by position. Hash each source file, record sheet/row or CSV row locators, and treat `outline_template_finance.xlsx` as comparison-only metadata. Parsing does not populate `standard_*`, assign quality tiers, or publish a field master.

- [ ] **Step 4: Run unit and integration tests**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_field_parsers.py -v`

Expected: GB2312 decoding, Excel sheet configs, raw value preservation, stable source IDs, frozen gate, and deterministic master output pass.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/fields tools/jrt0197_pipeline/schemas tools/jrt0197_pipeline/tests
git commit -m "feat: normalize heterogeneous finance fields"
```

## Task 10: Deterministic Mapping, A/B/C/D Quality, and English Eligibility

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/fields/mapping.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/fields/quality_tiers.py`
- Create: `tools/jrt0197_pipeline/config/semantic-evidence-1.0.0.yaml`
- Create: `tools/jrt0197_pipeline/config/english-eligibility-1.0.0.yaml`
- Create: `tools/jrt0197_pipeline/schemas/field-review-queue-1.0.0.schema.json`
- Modify: `tools/jrt0197_pipeline/src/jrt_pipeline/cli.py`
- Create: `tools/jrt0197_pipeline/tests/unit/test_field_mapping.py`
- Create: `tools/jrt0197_pipeline/tests/unit/test_quality_tiers.py`
- Create: `tools/jrt0197_pipeline/tests/unit/test_english_eligibility.py`
- Create: `tools/jrt0197_pipeline/tests/integration/test_generate_field_master.py`
- Modify: `tools/jrt0197_pipeline/tests/support/fields.py`
- Modify: `tools/jrt0197_pipeline/tests/fixtures/contracts/test-records.json`

**Interfaces:**
- Produces: `enumerate_candidates(field, rules) -> list[CandidateMatch]`.
- Produces: `evaluate_semantics(field, match, config) -> SemanticCheck`.
- Produces: `assign_quality(field, matches, semantic_check) -> MappingDecision`.
- Produces: `evaluate_english_name(field, config) -> EnglishEligibility`.
- Produces: `generate_field_master(frozen_dir: Path, sources: Sequence[SourceConfig], output_dir: Path) -> FieldMasterArtifacts` containing `finance_field_master.jsonl` and `finance_field_review_queue.jsonl`.
- CLI is exactly `generate-field-master --runtime-root PATH --frozen-version VERSION --dataset-version VERSION --sources-config PATH`.
- Only `MappingDecision.training_truth_allowed=True` may populate `standard_*`.

- [ ] **Step 1: Write failing B-tier uniqueness and C/D truth-null tests**

```python
def test_b_requires_unique_path_level_and_deterministic_evidence() -> None:
    decision = assign_quality(field("已结清不良贸易融资笔数", table="企业二代征信报告"), unique_matches(), passing_check())
    assert decision.quality_tier == "B"
    assert decision.mapping_status == "verified_after_completion"
    assert decision.training_truth_allowed is True


@pytest.mark.parametrize("status", ["ambiguous", "level_conflict", "no_rule_match"])
def test_unverified_records_never_receive_truth(status: str) -> None:
    decision = decision_for(status)
    assert decision.quality_tier in {"C", "D"}
    assert decision.standard_rule_id is None
    assert decision.minimum_security_level is None
```

- [ ] **Step 2: Run and verify mapping logic is missing**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_field_mapping.py tools/jrt0197_pipeline/tests/unit/test_quality_tiers.py tools/jrt0197_pipeline/tests/unit/test_english_eligibility.py`

Expected: missing mapping interfaces.

- [ ] **Step 3: Implement deterministic evidence and orthogonal states**

The semantic YAML contains version, rule-specific required terms, example terms, table context, exclusions, and approved synonyms. Fuzzy scores may appear only in `candidate_matches` ranking evidence.

```python
def can_upgrade_b(field: SourceFieldRecord, matches: Sequence[CandidateMatch], check: SemanticCheck) -> bool:
    return (
        len(matches) == 1
        and matches[0].path_is_unique
        and matches[0].level_is_unique
        and check.passed
        and not check.exclusion_terms_matched
        and check.alternative_candidate_count == 0
        and not field.source_conflicts
    )


def field(column_zh_name: str, *, table: str | None = None, **overrides: object) -> SourceFieldRecord:
    return make_contract(
        SourceFieldRecord,
        "source_field",
        column_zh_name=column_zh_name,
        table_zh_name=table,
        **overrides,
    )


def unique_matches() -> list[CandidateMatch]:
    return [CandidateMatch.from_mapping(value) for value in fixture_value("unique_matches")]


def passing_check() -> SemanticCheck:
    return make_contract(SemanticCheck, "passing_semantic_check")


def decision_for(status: str) -> MappingDecision:
    return make_contract(MappingDecision, f"mapping_decision_{status}")
```

Keep `quality_tier`, `mapping_status`, `verification_mode`, `reviewed`, and `review_status` separate. D statuses are exactly the six approved values. English eligibility accepts stable business tokens such as `ACCOUNT_BALANCE` and rejects random/internal patterns such as `UTFNUM`, `TJRGONH4`, `XKZ0031`, and `FIELD_A17`, recording evidence and config version.

Wire `generate-field-master` to validate the frozen manifest/master hash, parse configured sources, enumerate candidates, assign quality, and atomically publish both auditable files. A/B may receive `standard_*` only when `training_truth_allowed=true`; every C/D row in both outputs retains `candidate_matches[]` while all truth fields remain null. The review queue contains all C/D rows and reports conflict/ambiguity reasons from data; it never hard-codes the currently observed 32/53/85 counts.

- [ ] **Step 4: Run mapping tests**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_field_mapping.py tools/jrt0197_pipeline/tests/unit/test_quality_tiers.py tools/jrt0197_pipeline/tests/unit/test_english_eligibility.py tools/jrt0197_pipeline/tests/integration/test_generate_field_master.py -v`

Expected: exact A, verified B, ambiguous C, reasoned D, null truth for C/D, semantic evidence, and English allow/reject cases pass.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/fields tools/jrt0197_pipeline/src/jrt_pipeline/cli.py tools/jrt0197_pipeline/config tools/jrt0197_pipeline/schemas tools/jrt0197_pipeline/tests
git commit -m "feat: classify field mapping quality"
```

## Task 11: Deterministic Group-Constrained Splitting

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/splitting/__init__.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/splitting/constrained.py`
- Create: `tools/jrt0197_pipeline/config/splitting-1.0.0.yaml`
- Create: `tools/jrt0197_pipeline/tests/unit/test_constrained_split.py`
- Create: `tools/jrt0197_pipeline/tests/support/splitting.py`
- Modify: `tools/jrt0197_pipeline/tests/fixtures/contracts/test-records.json`
- Modify: `tools/jrt0197_pipeline/tests/conftest.py`

**Interfaces:**
- Produces: `constrained_split(samples: Sequence[SplitSample], config: SplitConfig) -> SplitResult`.
- `SplitResult.assignments` maps each `split_group_id` to `train|validation|test`.
- `SplitResult.audit` includes target/actual ratios, group counts, distribution deviation, uncovered categories/reasons, seed, and algorithm version.

- [ ] **Step 1: Write failing hard-constraint and determinism tests**

```python
def test_groups_never_cross_splits_and_result_is_deterministic(samples) -> None:
    first = constrained_split(samples, config(seed=20260723))
    second = constrained_split(list(reversed(samples)), config(seed=20260723))
    assert first.assignments == second.assignments
    assert group_intersections(first) == {"train_validation": [], "train_test": [], "validation_test": []}


def test_unsplittable_verified_field_is_supplemental() -> None:
    result = constrained_split([sample(split_group_id=None, split_eligible=False)], config())
    assert result.supplemental_sample_ids == ["field-1"]
```

- [ ] **Step 2: Confirm splitter is absent**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_constrained_split.py`

Expected: missing splitter failure.

- [ ] **Step 3: Implement deterministic greedy search with local improvement**

Use the explicit optimization target `train=80%`, `validation=10%`, and `test=10%`. Use `canonical_table_id` as the preferred field `split_group_id`, then an explicitly configured stable business entity/source group ID; never use the standard path as a field grouping key. Sort groups by stable SHA-256 of `algorithm_version|seed|group_id`, keep all variants together, preassign rare categories needed in training, then score candidate moves.

```python
def score(state: SplitState, target: Mapping[str, float]) -> tuple[float, float, float, float]:
    return (
        state.hard_constraint_violations,
        state.level_coverage_penalty,
        state.major_category_penalty,
        state.ratio_and_distribution_deviation(target),
    )


def sample(**overrides: object) -> SplitSample:
    return make_contract(SplitSample, "split_sample", **overrides)


def config(**overrides: object) -> SplitConfig:
    return make_contract(SplitConfig, "split_config", **overrides)


def group_intersections(result: SplitResult) -> dict[str, list[str]]:
    groups = {
        name: {group for group, split in result.assignments.items() if split == name}
        for name in ("train", "validation", "test")
    }
    return {
        "train_validation": sorted(groups["train"] & groups["validation"]),
        "train_test": sorted(groups["train"] & groups["test"]),
        "validation_test": sorted(groups["validation"] & groups["test"]),
    }
```

Reject every state with a hard violation. Optimize lexicographically, not with a weight that could trade leakage for ratio. Record impossible coverage with independent-group counts. Rules use `rule_id`; fields use stable business entities; standard path is never a field grouping key.

- [ ] **Step 4: Run adversarial grouping tests**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_constrained_split.py -v`

Expected: no group intersections, deterministic replay, soft 80%/10%/10% deviation reporting, rare-category retention, impossible-coverage reasons, and supplemental routing pass.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/splitting tools/jrt0197_pipeline/config tools/jrt0197_pipeline/tests/unit/test_constrained_split.py
git commit -m "feat: add constrained deterministic splitting"
```

## Task 12: Rule SFT, Task-Specific Outputs, and Sidecar Indexes

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/sft/__init__.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/sft/common.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/sft/rules.py`
- Modify: `tools/jrt0197_pipeline/src/jrt_pipeline/cli.py`
- Create: `tools/jrt0197_pipeline/schemas/sft-index-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/tests/unit/test_rule_sft.py`
- Create: `tools/jrt0197_pipeline/tests/integration/test_generate_rule_sft.py`
- Create: `tools/jrt0197_pipeline/tests/support/sft.py`
- Modify: `tools/jrt0197_pipeline/tests/fixtures/contracts/test-records.json`
- Modify: `tools/jrt0197_pipeline/tests/conftest.py`

**Interfaces:**
- Produces: `generate_rule_samples(rules: Sequence[FrozenRule]) -> list[IndexedSample]`.
- Produces: `deduplicate_samples(samples) -> DeduplicationResult`; conflicting identical inputs raise `ConflictingSupervisionError`.
- Defines: `SourceMapping(source_record_id: str, source_schema: str, source_file_sha256: str)` and `SftIndexEntry(line_number: int, sample_id: str, source_mappings: tuple[SourceMapping, ...], rule_id: str | None, task_type: str, quality_tier: str | None, split_group_id: str, sample_sha256: str)`.
- CLI is exactly `generate-rule-sft --runtime-root PATH --frozen-version VERSION --dataset-version VERSION` and creates the three `jrt0197_rule_sft_<split>.jsonl` files plus matching `.index.jsonl` files from a valid frozen version only.

- [ ] **Step 1: Write failing task-shape and conflict tests**

```python
def test_rule_task_outputs_are_fixed_by_task_type(frozen_rule) -> None:
    samples = {s.index.task_type: s for s in generate_rule_samples([frozen_rule])}
    assert list(samples["level_judgment"].alpaca) == ["instruction", "input", "output"]
    assert list(json.loads(samples["level_judgment"].alpaca["output"])) == ["minimum_security_level"]
    assert list(json.loads(samples["description_classification"].alpaca["output"])) == [
        "class1", "class2", "class3", "class4", "minimum_security_level",
    ]


def test_identical_input_with_different_output_blocks_generation() -> None:
    with pytest.raises(ConflictingSupervisionError):
        deduplicate_samples(conflicting_samples())


def test_deduplicated_index_retains_every_source_mapping() -> None:
    result = deduplicate_samples(same_supervision_from_two_sources())
    assert len(result.samples) == 1
    assert [m.source_record_id for m in result.samples[0].index.source_mappings] == ["field-001", "field-002"]


def test_rule_sft_cli_parses_then_requires_frozen_manifest(cli_runner, tmp_path) -> None:
    result = cli_runner(
        "generate-rule-sft", "--runtime-root", tmp_path, "--frozen-version", "not-frozen",
        "--dataset-version", "gate-check",
    )
    assert result.exit_code != 0
    assert "frozen_manifest_required" in result.stderr
    assert "unrecognized arguments" not in result.stderr
    assert not (tmp_path / "datasets" / "gate-check").exists()
```

- [ ] **Step 2: Run and confirm SFT generator is absent**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_rule_sft.py`

Expected: missing SFT interfaces.

- [ ] **Step 3: Implement three rule tasks, splitting, and one-to-one indexes**

```python
def alpaca_row(instruction: str, input_text: str, output: Mapping[str, object]) -> dict[str, str]:
    return {
        "instruction": instruction,
        "input": input_text,
        "output": json.dumps(output, ensure_ascii=False, separators=(",", ":")),
    }


def conflicting_samples() -> list[IndexedSample]:
    return [IndexedSample.from_mapping(value) for value in fixture_value("conflicting_samples")]


def same_supervision_from_two_sources() -> list[IndexedSample]:
    return [IndexedSample.from_mapping(value) for value in fixture_value("same_supervision_two_sources")]
```

Description classification and path completion output the full path plus level; level judgment outputs only level. All variants inherit `split_group_id=rule_id`. Each sidecar line uses this fixed schema order: `line_number`, `sample_id`, `source_mappings`, `rule_id`, `task_type`, `quality_tier`, `split_group_id`, `sample_sha256`. `source_mappings` is a deduplicated array of objects with `source_record_id`, `source_schema`, and `source_file_sha256`, sorted by `(source_schema, source_file_sha256, source_record_id)`; one SFT row still has exactly one index row. Deduplicate identical input/output while retaining every source mapping in the index; block differing outputs.

- [ ] **Step 4: Run synthetic frozen-version generation twice**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_rule_sft.py tools/jrt0197_pipeline/tests/integration/test_generate_rule_sft.py -v`

Expected: Alpaca files have exactly three keys, indexes align line-for-line, variants never cross splits, hashes replay identically, and pre-freeze generation fails without a dataset directory.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/sft tools/jrt0197_pipeline/src/jrt_pipeline/cli.py tools/jrt0197_pipeline/schemas tools/jrt0197_pipeline/tests
git commit -m "feat: generate traceable rule SFT"
```

## Task 13: Field SFT, Supplemental Datasets, English Thresholds, and Candidate-Review Entry Point

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/sft/fields.py`
- Create: `tools/jrt0197_pipeline/schemas/candidate-review-sft-1.0.0.schema.json`
- Create: `tools/jrt0197_pipeline/config/english-split-thresholds-1.0.0.yaml`
- Create: `tools/jrt0197_pipeline/tests/unit/test_field_sft.py`
- Create: `tools/jrt0197_pipeline/tests/integration/test_generate_field_sft.py`
- Modify: `tools/jrt0197_pipeline/tests/support/fields.py`
- Modify: `tools/jrt0197_pipeline/tests/fixtures/contracts/test-records.json`
- Modify: `tools/jrt0197_pipeline/tests/conftest.py`

**Interfaces:**
- Produces: `generate_chinese_field_samples(records) -> FieldSampleFamilies`.
- Produces: `generate_english_field_samples(records, thresholds) -> EnglishSampleFamilies`.
- Produces: `generate_candidate_review_samples(adjudications) -> list[IndexedSample]`, returning empty for no trusted adjudications and never fabricating negatives.
- CLI is exactly `generate-field-sft --runtime-root PATH --frozen-version VERSION --field-master-version VERSION --dataset-version VERSION`.

- [ ] **Step 1: Write failing input-contract and supplemental tests**

```python
def test_chinese_baseline_contains_no_label_candidate_or_english_data(verified_field) -> None:
    sample = generate_chinese_field_samples([verified_field]).splittable[0].alpaca
    assert sample["input"] == "表中文名：企业二代征信报告\n字段中文名：已结清不良贸易融资笔数"
    assert "候选" not in sample["input"] and "UTFNUM" not in sample["input"]


def test_verified_unsplittable_goes_only_to_supplemental(verified_field) -> None:
    verified_field.split_eligible = False
    family = generate_chinese_field_samples([verified_field])
    assert not family.splittable
    assert [s.index.source_mappings[0].source_record_id for s in family.supplemental] == [
        verified_field.source_record_id
    ]
```

- [ ] **Step 2: Verify field generator is absent**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_field_sft.py`

Expected: missing generator failure.

- [ ] **Step 3: Implement the three isolated field task families**

Chinese formal files accept A and deterministically verified B only, require stable groups, and contain Chinese table/field names only. Verified non-splittable records go solely to `finance_field_train_supplemental.jsonl`, disabled by default in the dataset manifest.

English records require verified truth and `english_sft_eligible=true`. Emit train/validation/test only if configured minimum independent group count, level coverage, major-category coverage, table diversity, and token diversity all pass; otherwise emit only `finance_field_english_supplemental.jsonl` and record every unmet threshold.

```python
def generate_candidate_review_samples(adjudications: Sequence[TrustedAdjudication]) -> list[IndexedSample]:
    if not adjudications:
        return []
    return [candidate_review_sample(item) for item in adjudications if item.review_status == "approved"]


def verified_field(**overrides: object) -> SourceFieldRecord:
    return make_contract(SourceFieldRecord, "verified_field", **overrides)
```

Never put confidence, provenance, original labels, evidence, or candidates in model input. Keep them in the sidecar indexes and field master.

- [ ] **Step 4: Run all field SFT cases**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/unit/test_field_sft.py tools/jrt0197_pipeline/tests/integration/test_generate_field_sft.py -v`

Expected: formal Chinese splits, disabled supplemental, English threshold fallback, empty candidate-review output, exact three-key Alpaca rows, and matching sidecar indexes pass.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/sft/fields.py tools/jrt0197_pipeline/schemas tools/jrt0197_pipeline/config tools/jrt0197_pipeline/tests
git commit -m "feat: generate verified field SFT families"
```

## Task 14: Cross-Artifact Audit and Complete Synthetic Lifecycle

**Files:**
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/audit/__init__.py`
- Create: `tools/jrt0197_pipeline/src/jrt_pipeline/audit/report.py`
- Create: `tools/jrt0197_pipeline/schemas/audit-report-1.0.0.schema.json`
- Modify: `tools/jrt0197_pipeline/src/jrt_pipeline/cli.py`
- Create: `tools/jrt0197_pipeline/tests/integration/test_synthetic_lifecycle.py`
- Create: `tools/jrt0197_pipeline/tests/integration/test_audit_failures.py`
- Create: `tools/jrt0197_pipeline/tests/support/lifecycle.py`
- Modify: `tools/jrt0197_pipeline/tests/fixtures/contracts/test-records.json`
- Modify: `tools/jrt0197_pipeline/tests/conftest.py`

**Interfaces:**
- Produces: `audit_runtime(runtime_root: Path, selection: DatasetSelection, evaluation_regime: str = "known_standard_unseen_field") -> AuditReport`.
- Defines: `DatasetSelection(rule_dataset_version: str, field_master_version: str, field_dataset_version: str)` so independently published artifact families can be audited together without mutating a dataset version.
- Defines: test-only `SyntheticDatasetVersion(runtime_root: Path, selection: DatasetSelection, rule_train_index: Path, rule_validation_index: Path)` in `tests/support/lifecycle.py`.
- Formal audit CLI is exactly `audit --runtime-root PATH --rule-dataset-version VERSION --field-master-version VERSION --field-dataset-version VERSION [--evaluation-regime known_standard_unseen_field]`.
- Produces: `audit_candidate(runtime_root: Path, run_id: str) -> CandidateAcceptanceReport` for read-only candidate completeness, preview inventory, state, and forbidden-output checks.
- `AuditReport.passed` is false for invalid frozen hashes, unresolved errors, conflicting supervision, or formal split-group overlap.
- Reports cross-rule/field `rule_id` intersections as disclosure in the default regime, not ordinary leakage.

- [ ] **Step 1: Write failing full-lifecycle and audit-gate tests**

```python
def test_synthetic_lifecycle_runs_every_command(synthetic_project) -> None:
    candidate = synthetic_project.candidate()
    reviewed = synthetic_project.approve(candidate)
    frozen = synthetic_project.freeze(reviewed)
    field_master = synthetic_project.generate_field_master(frozen)
    synthetic_project.generate_rule_sft(frozen)
    synthetic_project.generate_field_sft(field_master)
    report = synthetic_project.audit()
    assert report["passed"] is True
    assert report["evaluation_regime"] == "known_standard_unseen_field"


def test_audit_blocks_group_overlap(dataset_version) -> None:
    inject_group_overlap(dataset_version)
    report = audit_runtime(dataset_version.runtime_root, dataset_version.selection)
    assert report.passed is False
    assert "formal_group_overlap" in {finding.code for finding in report.findings}
```

- [ ] **Step 2: Run and confirm audit/lifecycle failure**

Run: `uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests/integration/test_synthetic_lifecycle.py tools/jrt0197_pipeline/tests/integration/test_audit_failures.py`

Expected: missing audit implementation or incomplete command wiring.

- [ ] **Step 3: Implement the audit report and wire all remaining CLI commands**

```python
BLOCKING_AUDIT_CODES = {
    "frozen_hash_invalid", "validation_error_unresolved", "conflicting_supervision",
    "formal_group_overlap", "manifest_schema_invalid", "index_alignment_invalid",
}


def require_success(result: CliResult) -> None:
    if result.exit_code != 0:
        raise AssertionError(f"CLI failed ({result.exit_code}): {result.stderr}")


def approve_every_synthetic_row(workbook: Path, reviewer: str, reviewed_at: str) -> None:
    book = openpyxl.load_workbook(workbook)
    sheet = book["候选规则"]
    headers = {cell.value: cell.column for cell in sheet[1]}
    for row in range(2, sheet.max_row + 1):
        if sheet.cell(row, headers["candidate_id"]).value is None:
            continue
        class4 = sheet.cell(row, headers["class4"]).value
        values = {
            "source_structure_decision": "not_applicable" if class4 else "confirmed_source_has_no_class4",
            "lineage_decision": "new_rule",
            "prior_rule_ids": "",
            "retained_rule_id": None,
            "review_decision": "approve",
            "review_comment": "synthetic fixture approval",
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
        }
        for column, value in values.items():
            sheet.cell(row, headers[column], value=value)
    book.save(workbook)


@dataclass
class SyntheticProject:
    runtime_root: Path
    pdf: Path
    sources_config: Path

    def candidate(self) -> Path:
        require_success(
            cli_runner(
                "candidate", "--pdf", self.pdf, "--runtime-root", self.runtime_root, "--run-id", "synthetic"
            )
        )
        return self.runtime_root / "candidate" / "synthetic"

    def approve(self, candidate: Path) -> Path:
        reviewed = self.runtime_root / "reviews" / "synthetic-approved.xlsx"
        reviewed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate / "jrt0197_rule_review.xlsx", reviewed)
        approve_every_synthetic_row(reviewed, reviewer="synthetic-reviewer", reviewed_at="2026-07-23T12:00:00Z")
        return reviewed

    def freeze(self, reviewed: Path) -> Path:
        require_success(cli_runner(
            "freeze", "--runtime-root", self.runtime_root, "--candidate-run-id", "synthetic",
            "--reviewed-workbook", reviewed, "--version", "1.0.0", "--approved-by", "synthetic-approver",
            "--approved-at", "2026-07-23T12:30:00Z", "--approval-note", "synthetic fixture approval",
            "--approval-scope", "physical pages 17-19 synthetic Table A.1",
        ))
        return self.runtime_root / "frozen" / "1.0.0"

    def generate_field_master(self, frozen: Path) -> Path:
        require_success(cli_runner(
            "generate-field-master", "--runtime-root", self.runtime_root, "--frozen-version", frozen.name,
            "--dataset-version", "field-master-1", "--sources-config", self.sources_config,
        ))
        return self.runtime_root / "datasets" / "field-master-1"

    def generate_rule_sft(self, frozen: Path) -> Path:
        require_success(cli_runner(
            "generate-rule-sft", "--runtime-root", self.runtime_root, "--frozen-version", frozen.name,
            "--dataset-version", "rule-sft-1",
        ))
        return self.runtime_root / "datasets" / "rule-sft-1"

    def generate_field_sft(self, field_master: Path) -> Path:
        require_success(cli_runner(
            "generate-field-sft", "--runtime-root", self.runtime_root, "--frozen-version", "1.0.0",
            "--field-master-version", field_master.name, "--dataset-version", "field-sft-1",
        ))
        return self.runtime_root / "datasets" / "field-sft-1"

    def audit(self) -> dict[str, object]:
        result = cli_runner(
            "audit", "--runtime-root", self.runtime_root, "--rule-dataset-version", "rule-sft-1",
            "--field-master-version", "field-master-1", "--field-dataset-version", "field-sft-1",
            "--evaluation-regime", "known_standard_unseen_field",
        )
        require_success(result)
        return json.loads(result.stdout)


def inject_group_overlap(dataset_version: SyntheticDatasetVersion) -> None:
    train_index = read_jsonl(dataset_version.rule_train_index)
    validation_index = read_jsonl(dataset_version.rule_validation_index)
    validation_index[0]["split_group_id"] = train_index[0]["split_group_id"]
    write_jsonl(
        dataset_version.rule_validation_index,
        validation_index,
        load_schema("sft-index-1.0.0"),
    )
```

Audit file/source/config/output hashes; counts and ratios; independent groups; 1–4 levels; class1/class2/full-path coverage; distribution deviation; impossible coverage; duplicates; split intersections; seed/algorithm; supplemental enabled state; English thresholds; forbidden outputs; and rule/field rule-ID intersections. Dataset manifests use `<dataset_family>_manifest.json` and publish atomically. Wire `audit --candidate-run-id ID --candidate-only` to `audit_candidate`; this mode is read-only, accepts only `awaiting_review`, verifies the page-evidence JSONL hash, ordered PNG-set hash/count, ownership/unassigned counts, both lineage manifests, every required candidate file, and the separate `previews/workbook/` inventory, checks forbidden formal paths, and never creates a dataset manifest.

Add negative lifecycle cases for workbook mismatch, unauthorized edit, real-rule rejection, body `unassigned`, unconfirmed class4, conflicting identical input, split overlap, pre-freeze SFT request, invalid master hash, and insufficient English groups.

- [ ] **Step 4: Run the complete synthetic suite and deterministic replay**

Run:

```powershell
uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests
make jrt-quality
make jrt-license
```

Expected: all synthetic commands and negative gates pass; two independent synthetic runs have byte-identical core artifacts; only `run_metadata.json` may differ without `SOURCE_DATE_EPOCH`.

- [ ] **Step 5: Commit**

```powershell
git add tools/jrt0197_pipeline/src/jrt_pipeline/audit tools/jrt0197_pipeline/src/jrt_pipeline/cli.py tools/jrt0197_pipeline/schemas tools/jrt0197_pipeline/tests
git commit -m "feat: audit the complete synthetic pipeline"
```

## Task 15: Real Candidate Run, Visual Verification, and Forbidden-Artifact Acceptance

**Files:**
- Create outside Git: `D:\work\2026.7.13_微调\jrt0197_pipeline_outputs\candidate\<run_id>\`
- Do not modify: any file under `D:\work\2026.7.13_微调\data\`
- Do not create: any real-data path under `<runtime_root>\frozen\` or `<runtime_root>\datasets\`

**Interfaces:**
- Consumes the real PDF only: `D:\work\2026.7.13_微调\data\金融数据安全 数据安全分级指南JRT 0197—2020.pdf`.
- Produces one immutable candidate directory in state `awaiting_review`.
- This task does not consume the real CSV/XLSX files because real field processing is after freeze and is outside this run boundary.

- [ ] **Step 1: Verify the implementation and capture source hashes before the real run**

Run:

```powershell
git status --short
uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests
make jrt-quality
make jrt-license
Get-FileHash -Algorithm SHA256 -LiteralPath 'D:\work\2026.7.13_微调\data\金融数据安全 数据安全分级指南JRT 0197—2020.pdf'
```

Expected: clean worktree; all synthetic checks pass; source hash is recorded in the run notes before execution.

- [ ] **Step 2: Run only the real candidate command**

Choose a new UTC-derived run ID, for example `20260723T120000Z`, and run:

```powershell
uv run --project tools/jrt0197_pipeline python tools/jrt0197_pipeline/pipeline.py candidate `
  --pdf 'D:\work\2026.7.13_微调\data\金融数据安全 数据安全分级指南JRT 0197—2020.pdf' `
  --runtime-root 'D:\work\2026.7.13_微调\jrt0197_pipeline_outputs' `
  --run-id '20260723T120000Z'
```

Expected: exit 0 and exactly one new candidate snapshot. If validation reports an error, retain only a failed diagnostic run outside the approvable namespace, fix code/config with a new tested commit, and rerun under a new run ID. Never relax the validator or edit the snapshot.

- [ ] **Step 3: Verify candidate completeness and visually inspect every workbook sheet**

Run the read-only acceptance command:

```powershell
uv run --project tools/jrt0197_pipeline python tools/jrt0197_pipeline/pipeline.py audit `
  --runtime-root 'D:\work\2026.7.13_微调\jrt0197_pipeline_outputs' `
  --candidate-run-id '20260723T120000Z' `
  --candidate-only
```

Expected: pages 17–51 represented and rendered; zero validation errors; `evidence/jrt0197_page_evidence.jsonl`, exactly 35 `evidence/pages/physical-page-*.png` files, candidate JSONL, named manifest, validation report, diff, workbook, and all `previews/workbook/` images present. Manifest `page_evidence_jsonl_sha256`, `page_png_set_sha256`, `page_count=35`, `ownership_block_count`, and `unassigned_block_count` verify; `pipeline_state=awaiting_review`. Open every workbook preview and verify readable headers/body text, nonblank sheets, matching counts, visible review columns, severity formatting, and intact metadata; inspect PDF evidence images separately from workbook previews.

- [ ] **Step 4: Prove formal commands are gated and leave no forbidden artifacts**

Run the valid formal CLI with a nonexistent frozen version; this must pass argument parsing and fail inside the frozen-master gate:

```powershell
$gateOutput = uv run --project tools/jrt0197_pipeline python tools/jrt0197_pipeline/pipeline.py generate-rule-sft `
  --runtime-root 'D:\work\2026.7.13_微调\jrt0197_pipeline_outputs' `
  --frozen-version 'not-frozen' `
  --dataset-version 'gate-check' 2>&1
$gateExit = $LASTEXITCODE
if ($gateExit -eq 0) { throw "Formal command unexpectedly succeeded" }
if (($gateOutput -join "`n") -notmatch 'frozen_manifest_required') {
  throw "Command did not reach the frozen-manifest gate"
}

$root = 'D:\work\2026.7.13_微调\jrt0197_pipeline_outputs'
if (Test-Path -LiteralPath "$root\datasets\gate-check") {
  throw "Failed gate left a partial dataset version"
}
$forbidden = @(
  "$root\frozen", "$root\datasets"
) + (Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
  $_.Name -eq 'jrt0197_rule_master.jsonl' -or
  $_.Name -like 'jrt0197_rule_sft_*.jsonl' -or
  $_.Name -like 'finance_field_verified_*.jsonl'
}).FullName
if ($forbidden | Where-Object { Test-Path -LiteralPath $_ }) { throw "Forbidden formal artifact exists" }
```

Expected: argument parsing succeeds, the command enters frozen-master validation, exits nonzero with `frozen_manifest_required`, and does not create `datasets/gate-check` or any other formal artifact; the PowerShell assertions exit 0.

- [ ] **Step 5: Record acceptance without committing real artifacts**

Add the run ID, source PDF hash, candidate manifest hash, validation status, preview checklist result, and forbidden-artifact result to the external run notes. Then prove the runtime root is outside the repository and inspect Git state:

```powershell
$repo = [System.IO.Path]::GetFullPath((git rev-parse --show-toplevel))
$runtime = [System.IO.Path]::GetFullPath('D:\work\2026.7.13_微调\jrt0197_pipeline_outputs')
if ($runtime.StartsWith($repo + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Runtime root is inside the Git repository"
}
git status --short
```

Expected: no real data or output is staged or tracked. Do not commit the external run notes or candidate assets.

---

## Final Verification Gate

Before claiming implementation completion, invoke `superpowers:verification-before-completion` and run fresh evidence:

```powershell
uv sync --project tools/jrt0197_pipeline --frozen --group dev
uv run --project tools/jrt0197_pipeline pytest -q tools/jrt0197_pipeline/tests
make jrt-quality
make jrt-license
git diff --check
git status --short
```

With the configured bundled workbook runtime, also run:

```powershell
$env:JRT0197_NODE_MODULES='<bundled-node-modules-root>'
npm --prefix tools/jrt0197_pipeline test
```

The implementation is acceptable only when synthetic full-lifecycle tests pass, the real candidate is `awaiting_review`, all previews have been visually inspected, the pre-freeze formal command is rejected, and no real frozen or dataset artifact exists.
