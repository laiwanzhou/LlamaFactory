# JR/T 0197—2020 Table A.1 Reproducible Data Pipeline Design

Date: 2026-07-23
Status: Approved design; implementation planning not yet started

## 1. Purpose and authority

Build a reproducible pipeline that extracts and verifies Table A.1, “金融业机构典型数据定级规则参考表,” from `金融数据安全 数据安全分级指南JRT 0197—2020.pdf`, then uses a human-approved frozen rule master to normalize heterogeneous field records and generate auditable LLaMA Factory datasets.

Table A.1 is the sole semantic truth source. Existing templates, CSV labels, training workbooks, audit scripts, and result workbooks are untrusted sample or comparison sources. They may reveal discrepancies but may never modify the standard automatically.

The project covers only levels 1–4. Level 5 is not extracted, trained, evaluated, or used for rejection samples. Documentation records it only as out of scope. If scoped extraction detects an out-of-range level, candidate publication fails rather than silently filtering or downgrading it.

## 2. Current-run boundary

The full pipeline will be implemented and tested, but real data may run only through:

```text
extract → validate → build-review → awaiting_review
```

This run produces candidate rules, validation and difference reports, page evidence, and a review workbook, then stops for independent human review. `freeze`, rule/field SFT generation, field mapping, splitting, and final audit are tested only with synthetic fixtures.

Acceptance explicitly proves that no `outputs/frozen/**`, `outputs/datasets/**`, `jrt0197_rule_master.jsonl`, `jrt0197_rule_sft_*.jsonl`, or `finance_field_verified_*.jsonl` real-data artifact exists.

## 3. Repository and data isolation

The independent repository is `D:\work\2026.7.13_微调\jrt0197_pipeline`. It contains source, versioned configuration, schemas, documentation, dependency locks, tests, and synthetic/minimized fixtures only.

The existing `data` directory, `tmp/audit`, and historical result workbooks remain read-only outside the repository. Real PDF, XLSX, CSV, JSONL, logs, workbooks, previews, and outputs are excluded from Git. `.gitattributes` fixes LF for text and marks binary artifacts explicitly.

## 4. Architecture and responsibilities

Python owns CLI orchestration, semantics, extraction, normalization, validation, hashing, approval enforcement, permanent IDs, field mapping, quality tiers, SFT generation, splitting, and audit decisions. JavaScript only reads Python-produced contracts to generate and render the review workbook.

```text
pipeline.py
src/jrt_pipeline/
  cli.py
  contracts.py
  hashing.py
  normalization.py
  extraction/table_a1.py
  validation/rules.py
  review/contract.py
  freeze/service.py
  fields/parsers.py
  fields/mapping.py
  fields/quality_tiers.py
  sft/rules.py
  sft/fields.py
  splitting/constrained.py
  audit/report.py
tools/build_review.mjs
schemas/
tests/fixtures/
tests/unit/
tests/integration/
docs/superpowers/specs/
outputs/
```

JavaScript may create tables/styles, add review columns, apply conditional formatting, and render previews. It may not rewrite a path or rule, decide a level, calculate semantic fingerprints, approve records, or allocate permanent IDs.

## 5. CLI and state model

The unified Python CLI exposes:

```text
extract
validate
build-review
freeze
generate-rule-sft
generate-field-master
generate-field-sft
audit
candidate
```

`candidate` runs `extract → validate → build-review` and stops. State is attached to immutable artifacts:

```text
outputs/candidate/<run_id>/manifest.json
outputs/frozen/<version>/manifest.json
outputs/datasets/<version>/manifest.json
```

Candidate state ends at `awaiting_review`. Freeze creates a new version; it never edits a candidate snapshot.

Outputs are written under a same-volume sibling such as `outputs/candidate/.tmp-<run_id>/`, verified, then renamed into place. Existing targets fail, no overwrite option exists, and every run uses a new ID. Read-only file attributes are only supplemental protection.

## 6. Table A.1 extraction

The physical range is fixed at PDF pages 17–51 inclusive. Extraction renders each page, captures text/cells/coordinates/table boundaries, removes repeated headers, reconstructs continued rows and merged-cell inheritance, and emits ordered candidate records.

Every source block or cell is classified as `table_header`, `rule_content`, `page_footer`, `note`, `explicitly_ignored`, or `unassigned`. Unassigned content inside the table body is an error; any other unassigned content is at least a high-priority warning.

Cross-page rules use `source_fragments[]`, with page, row locator, and bounding boxes for each fragment, plus start/end page fields. A compatibility `source_physical_page` may equal the start page, but fragments are authoritative. Inherited values record their source and reason. Missing-source, circular, or implicit inheritance is an error.

If the source genuinely lacks a fourth-level category, the candidate stores `class4=null`, `path_depth=3`, `source_structure_status=unconfirmed_missing_class4`, and `missing_class4_from_source`. It cannot freeze or generate SFT until review marks `confirmed_source_has_no_class4`; an extraction error requires a new candidate. No class name is invented.

## 7. Normalization, identity, and hashing

Allowed normalization trims outer whitespace, joins PDF layout line breaks, normalizes repeated whitespace/newlines, applies a versioned full-/half-width punctuation map, represents missing values as `null`, and parses levels as integers.

It must not replace synonyms, rewrite standard language, auto-correct suspected typos, delete repeated-looking sentences, merge rules, or repair PDF text from an Excel/template source.

Raw extraction, raw cells, normalized semantic fields, coordinates, and inheritance traces are retained.

Candidates receive run-local IDs such as `CAND-A1-0001`; they are not stable across runs. Permanent IDs such as `JRT0197-A1-0001` are allocated only at freeze and never globally renumbered. Later discoveries receive trailing IDs; `source_order` stores current table order.

The semantic fingerprint is SHA-256 over canonical fixed-order JSON containing only `class1`, `class2`, `class2_definition`, `class3`, `class3_definition`, `class4`, `class4_description`, `minimum_security_level`, and `note`. IDs, timestamps, tool versions, pages, coordinates, and evidence are excluded. Separate hashes cover the source PDF, page PNGs, raw cells, and source fragments.

## 8. Candidate artifacts and differences

Each immutable snapshot contains:

```text
outputs/candidate/<run_id>/
  jrt0197_rule_master_candidate.jsonl
  jrt0197_rule_candidate_manifest.json
  jrt0197_rule_validation_report.json
  jrt0197_rule_diff.json
  jrt0197_rule_review.xlsx
  previews/
```

JSONL contains records only. The manifest records schema/extraction/normalization/fingerprint versions, run ID, source hash, page range, deterministic tool versions, record count, JSONL hash, comparison baseline, validation state, and pipeline state. Non-deterministic run timing/host data lives in `run_metadata.json`, or uses `SOURCE_DATE_EPOCH` where required.

Diff compares against the latest frozen master, otherwise the latest prior candidate, otherwise reports `baseline_status=no_baseline`.

## 9. Validation

Findings use `error`, `warning`, or `info`. Errors include out-of-range/unparsable levels, missing source pages, invalid inheritance, identical paths with different levels, unassigned table-body content, unconfirmed structural absence, invalid hashes, and schema failures. Baseline count/distribution changes are warnings until explained. Same fourth-level names on different paths and minor layout changes are info or warnings according to ambiguity risk.

Candidate snapshots may contain warnings. Errors prevent an approvable workbook. An explicit diagnostic mode may generate a workbook labeled `diagnostic_only`, which cannot freeze.

Validation covers all scoped pages, continued headers, source order and locators, evidence, inheritance, raw/normalized fields, fingerprints, duplicate rules, path-level conflicts, path discontinuities, and computed level distributions. Counts are never hard-coded.

## 10. Review workbook and approval

The workbook contains `审核说明`, `候选规则`, `自动校验问题`, `差异对照`, `统计汇总`, `候选清单`, and hidden/protected `__review_metadata`.

Metadata stores run ID, candidate and manifest hashes, review schema version, editable columns, candidate count, and candidate-ID-set hash. It is not a security boundary; Python compares every immutable row/cell to candidate JSONL on import.

Editable semantic proposals are limited to `class1..class4`, `class2_definition`, `class3_definition`, `class4_description`, `minimum_security_level`, and `note`, plus decision metadata. Candidate ID, order, source pages/locators, raw extraction, inheritance, and hashes are immutable. Incorrect source evidence requires re-extraction.

Row decisions are `approve`, `modify`, `reject_as_extraction_artifact`, `reject_as_duplicate`, or `reject_requires_reextraction`. Excluded artifacts/duplicates remain audited. Rejecting a real Table A.1 rule blocks freeze.

Every row records decision, comment, reviewer, and reviewed time. Freeze also requires whole-run `approved_by`, `approved_at`, `approval_note`, and `approval_scope`, confirming complete page coverage and suitability as a truth baseline.

## 11. Freeze

Freeze verifies candidate/manifest/workbook hashes, metadata, candidate IDs, immutable cells, row decisions, and whole-run approval. Python applies only whitelisted proposals, then re-normalizes, revalidates, recalculates fingerprints, and allocates/reuses permanent IDs. It never copies Excel cells directly into truth.

Success creates a new immutable version with `jrt0197_rule_master.jsonl`, `jrt0197_rule_id_map.json`, `jrt0197_rule_manifest.json`, and `jrt0197_rule_master.sha256`. The manifest records frozen version/state, approvals, source/master hashes, computed count, tool/contract versions, and passed validation. Later fixes use a new candidate and review.

## 12. Field master and source parsing

Each heterogeneous source uses an explicit `source_schema` parser. Initial schemas cover the GB2312 finance CSV and separately configured `train_data.xlsx` sheets. Parsers validate required columns and exact source locations; they do not infer positional schemas silently.

The outline template is comparison-only. Historical outputs are audit-only. Neither becomes training input or truth.

`finance_field_master.jsonl` keeps source identity/hashes, raw and normalized names/paths, `provided_level_raw`, parsed level/status, candidate matches, verified standard fields, quality/mapping/verification/review states, split grouping, and English eligibility. `provided_*` remains immutable.

C/D records keep possible rules only in `candidate_matches[]`; `standard_rule_id`, `standard_class1..4`, and `minimum_security_level` remain null. Only A and fully verified B records may populate standard truth.

## 13. Mapping and quality tiers

Mapping runs: exact path/level; exact path with conflict detection; fourth-level candidate enumeration; versioned deterministic Chinese evidence checks; then ambiguity/conflict/no-match classification.

Generative models cannot assign truth. Fuzzy or embedding similarity may rank candidates but never independently pass verification.

Tier A requires one frozen rule with agreeing path, level, and field semantics. Tier B may complete a path only when fourth-level name, full path, and level are unique; deterministic Chinese evidence passes; source fields do not conflict; and no plausible alternative remains. Evidence includes rule ID/path/level, method, matched terms, PDF page, exclusions, alternatives, and check version.

Deterministic evidence may use exact Table A.1 examples, approved synonyms, required table context and field terms, and exclusion terms. All dictionaries/rules are versioned.

Tier C is plausible but insufficient/ambiguous. Tier D distinguishes `conflicting_annotation`, `level_conflict`, `path_conflict`, `source_internal_conflict`, `no_rule_match`, and `invalid_source_record`. Quality tier, deterministic verification, and human review are orthogonal. C/D and all identified conflict/ambiguity records enter the review queue without truth. This explicitly includes the currently known 32 conflicts and 53 cross-path/cross-level ambiguities; all 85 remain outside formal training until adjudicated.

## 14. SFT contracts

Only training files use Alpaca JSONL with exactly `instruction`, `input`, and `output`. Master/review JSONL keeps audit schemas.

Chinese baseline input contains only `表中文名` and `字段中文名`; it never contains original labels, candidates, confidence, evidence, or opaque English codes. Output is fixed-order JSON with `class1..class4` and `minimum_security_level`.

English supplemental samples require verified A/B truth and clearly interpretable business names. Versioned token/rejection rules exclude random strings, internal codes, serials, and unexplained abbreviations. English data is disabled by default.

Candidate-review SFT implements schema, validation, an empty generator entry point, and adjudication import only. It does not create real samples or synthetic negatives before trusted human outcomes exist.

Rule description-classification and path-completion tasks output full path plus level. Level-judgment tasks output only `minimum_security_level`. All variants of one rule inherit one split group.

Formal and supplemental SFT filenames are:

```text
jrt0197_rule_sft_train.jsonl
jrt0197_rule_sft_validation.jsonl
jrt0197_rule_sft_test.jsonl
finance_field_verified_train.jsonl
finance_field_verified_validation.jsonl
finance_field_verified_test.jsonl
finance_field_train_supplemental.jsonl
finance_field_english_train.jsonl
finance_field_english_validation.jsonl
finance_field_english_test.jsonl
finance_field_english_supplemental.jsonl
```

Verified but non-splittable A/B fields go only to disabled-by-default `finance_field_train_supplemental.jsonl`. English train/validation/test files are created only when the independent-coverage threshold in Section 15 is met; otherwise only the English supplemental file is produced.

Every Alpaca file has a same-order `<dataset>.index.jsonl` with line number, sample/source/rule IDs, task type, quality tier where applicable, split group, and sample hash.

## 15. Grouping, splitting, and evaluation

The target is 80%/10%/10%, not a hard ratio. Hard constraints are intact groups, shared assignment for variants, exclusion of `split_eligible=false` from validation/test, exclusion of review records, and deterministic replay.

Rules group by `rule_id`. Fields group by a stable business entity such as `canonical_table_id` or documented source group ID. Standard path is stratification only, never a general field grouping key. Verified ungroupable fields become optional training supplements.

The solver prioritizes training coverage, feasible 1–4 coverage, major first-level and high-frequency second-level categories, and rare-category retention in training; then it minimizes ratio/distribution deviation. Major categories consider sample and independent-group counts. Impossible coverage is reported, never “fixed” by splitting groups.

English variants inherit field assignments. Formal English validation/test is emitted only when independent groups, levels/categories, table diversity, and lexical diversity satisfy configured minimums. Otherwise only `finance_field_english_supplemental.jsonl` is emitted and no English generalization claim is made.

Default joint evaluation is `evaluation_regime=known_standard_unseen_field`: the standard is known, while field tests measure unseen business entities/fields. Rule-task tests measure format/recall, not unseen-rule generalization. Audits disclose rule-ID intersections across rule/field datasets. A future strict unseen-rule regime must coordinate both splitters.

## 16. Determinism, duplicates, and audit

Core artifacts use UTF-8, LF, fixed key/record order, fixed Unicode escaping, stable number/null encoding, fixed pre-split group order, fixed seed, and versioned algorithm. Runtime timestamps and host data are separate.

Duplicate handling distinguishes: identical input/output from one source variant (deduplicate and record); identical input/output across sources (deduplicate but retain all source mappings); and identical model input with different outputs (block generation and send to review).

Each dataset receives manifest/audit data covering input/config/output hashes, counts, ratios, groups, levels, category/path coverage, distribution deviation, unmet constraints, group intersections, duplicate outcomes, seed/algorithm, supplemental status, and cross-task rule-ID intersections.

Invalid frozen hashes, unhandled errors, conflicting supervision, or forbidden group overlap blocks publication.

## 17. Workbook quality and testing

The JavaScript builder uses the bundled workbook runtime, professional restrained formatting, filters, frozen panes, severity highlighting, review-column styling, and clear instructions. All sheets are rendered and visually inspected; clipping, unreadable text, blank/broken sheets, count mismatch, missing metadata, conditional-formatting defects, or formula errors must be fixed.

Unit tests cover normalization, fingerprints/evidence hashes, continuation/inheritance, content assignment, severity, approval/rejection, parsers, tiers, deterministic evidence, English eligibility, duplicates, and splitting. Contract tests cover schemas, deterministic serialization, manifests, workbook immutability, row approval, and whole-run approval.

Integration tests use synthetic PDF/CSV/XLSX/candidate/review/frozen fixtures. End-to-end tests execute every command on synthetic data only. Negative tests include workbook mismatch, unauthorized edits, rejection of a real rule, unassigned body content, unconfirmed missing `class4`, conflicting identical model input, split overlap, pre-freeze SFT generation, and insufficient English grouping.

## 18. Real candidate acceptance

Completion requires pages 17–51 represented/rendered; extraction, ownership, inheritance, normalization, and hashes passing with no errors; candidate JSONL/manifest/validation/diff/workbook/previews present; every user-facing sheet visually verified; immutable candidate publication; `awaiting_review` state; forbidden formal artifacts absent; and a pre-freeze formal command failing without partial output.

## 19. Non-goals

This version does not extract/train level 5, use PDF prose outside Table A.1 as truth, treat template/CSV labels as authority, manufacture labels with a generative model, synthesize candidate-review negatives, edit source evidence through Excel, overwrite versions, claim unseen-rule generalization in the default regime, or execute real-data freeze/SFT generation before later explicit approval.
