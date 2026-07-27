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

from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

from ..contracts import PageEvidence, RuleCandidate, read_jsonl
from ..hashing import file_sha256


def _finding(
    severity: str,
    code: str,
    message: str,
    candidate: RuleCandidate | None = None,
    physical_page: int | None = None,
) -> dict[str, object]:
    return {
        "severity": severity,
        "code": code,
        "candidate_id": candidate.candidate_id if candidate else None,
        "physical_page": physical_page
        if physical_page is not None
        else (candidate.source_physical_page if candidate else None),
        "message": message,
    }


def validate_candidates(
    records: Sequence[RuleCandidate],
    evidence: Sequence[PageEvidence],
    *,
    page_start: int = 17,
    page_end: int = 51,
    comparison: dict[str, object] | None = None,
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    pages = {page.physical_page for page in evidence}
    expected_pages = set(range(page_start, page_end + 1))
    for missing in sorted(expected_pages - pages):
        findings.append(_finding("error", "source_page_missing", f"物理页 {missing} 缺失", physical_page=missing))
    for page in evidence:
        for block in page.blocks:
            if block.in_table_body and block.ownership == "unassigned":
                findings.append(
                    _finding(
                        "error",
                        "unassigned_table_body",
                        f"表格主体块未归属: {block.block_id}",
                        physical_page=page.physical_page,
                    )
                )

    expected_orders = list(range(1, len(records) + 1))
    actual_orders = [record.source_order for record in records]
    if actual_orders != expected_orders:
        findings.append(_finding("error", "source_order_not_contiguous", "source_order 不连续或顺序错误"))

    seen_locators: set[tuple[int, str]] = set()
    fingerprints: defaultdict[str, list[RuleCandidate]] = defaultdict(list)
    paths: defaultdict[tuple[str | None, ...], set[int | None]] = defaultdict(set)
    class4_paths: defaultdict[str, set[tuple[str | None, ...]]] = defaultdict(set)
    evidence_locators = {
        (page.physical_page, str(cell["row_locator"]))
        for page in evidence
        for cell in page.raw_cells
        if cell.get("row_locator")
    }
    for record in records:
        locator = (record.source_physical_page, record.source_row_locator)
        if locator in seen_locators:
            findings.append(_finding("error", "source_locator_duplicate", "来源页码与行定位重复", record))
        seen_locators.add(locator)
        if not record.source_fragments:
            findings.append(_finding("error", "source_fragment_missing", "未保存来源片段", record))
        for fragment in record.source_fragments:
            if (fragment.physical_page, fragment.row_locator) not in evidence_locators:
                findings.append(
                    _finding(
                        "error",
                        "source_fragment_unresolved",
                        "来源片段无法在页级证据中定位",
                        record,
                        fragment.physical_page,
                    )
                )
        for trace in record.inheritance_trace:
            source = (int(trace["source_physical_page"]), str(trace["source_row_locator"]))
            if source not in evidence_locators:
                findings.append(
                    _finding("error", "inheritance_source_missing", "继承来源无法在页级证据中定位", record)
                )
        if record.minimum_security_level_parse_status == "unparseable" or record.minimum_security_level is None:
            findings.append(_finding("error", "level_unparseable", "最低安全级别无法解析", record))
        elif record.minimum_security_level not in {1, 2, 3, 4}:
            findings.append(_finding("error", "level_out_of_scope", "最低安全级别不在 1—4 范围", record))
        if record.class4 is None:
            findings.append(
                _finding("error", "missing_class4_from_source", "PDF 来源未提供四级子类，需人工确认源结构", record)
            )
        if not record.raw_extraction:
            findings.append(_finding("error", "raw_extraction_missing", "原始提取内容为空", record))
        if not record.normalized_content:
            findings.append(_finding("error", "normalized_content_missing", "规范化内容为空", record))
        if not record.candidate_fingerprint.startswith("sha256:"):
            findings.append(_finding("error", "candidate_fingerprint_missing", "候选语义指纹缺失", record))
        fingerprints[record.candidate_fingerprint].append(record)
        path = (record.class1, record.class2, record.class3, record.class4)
        paths[path].add(record.minimum_security_level)
        if record.class4:
            class4_paths[record.class4].add(path)

    for fingerprint, matches in fingerprints.items():
        if fingerprint and len(matches) > 1:
            findings.append(
                _finding("warning", "duplicate_fingerprint", f"候选指纹重复，共 {len(matches)} 条", matches[0])
            )
    for path, levels in paths.items():
        if len(levels) > 1:
            findings.append(
                _finding(
                    "error",
                    "path_level_conflict",
                    f"相同完整路径对应不同级别: {sorted(level for level in levels if level is not None)}",
                )
            )
    for class4, distinct_paths in class4_paths.items():
        if len(distinct_paths) > 1:
            findings.append(
                _finding(
                    "info", "same_class4_multiple_paths", f"四级子类“{class4}”出现在 {len(distinct_paths)} 条路径"
                )
            )
    if len(records) != 302:
        findings.append(
            _finding(
                "warning",
                "historical_count_hint_mismatch",
                f"实际提取 {len(records)} 条；既有审计提示约 302 条，请人工核对",
            )
        )

    severity_count = Counter(str(finding["severity"]) for finding in findings)
    level_distribution = Counter(
        str(record.minimum_security_level) for record in records if record.minimum_security_level is not None
    )
    return {
        "schema_name": "jrt0197_rule_validation_report",
        "schema_version": "1.0.0",
        "validation_status": "failed" if severity_count["error"] else "passed",
        "error_count": severity_count["error"],
        "warning_count": severity_count["warning"],
        "info_count": severity_count["info"],
        "findings": findings,
        "page_coverage": {
            "physical_page_start": page_start,
            "physical_page_end": page_end,
            "expected_count": page_end - page_start + 1,
            "actual_pages": sorted(pages),
            "missing_pages": sorted(expected_pages - pages),
        },
        "record_count": len(records),
        "level_distribution": dict(sorted(level_distribution.items())),
        "source_order_contiguous": actual_orders == expected_orders,
        "source_locator_unique": len(seen_locators) == len(records),
        "duplicate_fingerprint_count": sum(len(items) > 1 for items in fingerprints.values()),
        "path_level_conflict_count": sum(len(levels) > 1 for levels in paths.values()),
        "missing_class4_count": sum(record.class4 is None for record in records),
        "unassigned_table_body_count": sum(
            block.in_table_body and block.ownership == "unassigned" for page in evidence for block in page.blocks
        ),
        "comparison": comparison or {"baseline_status": "not_evaluated"},
    }


def _candidate_baseline(directory: Path) -> tuple[list[dict[str, object]], dict[str, object]] | None:
    master = directory / "jrt0197_rule_master_candidate.jsonl"
    manifest = directory / "jrt0197_rule_candidate_manifest.json"
    if not master.is_file() or not manifest.is_file():
        return None
    return read_jsonl(master), {
        "baseline_type": "candidate",
        "baseline_id": directory.name,
        "baseline_hash": file_sha256(master),
        "manifest_hash": file_sha256(manifest),
    }


def _frozen_baseline(directory: Path) -> tuple[list[dict[str, object]], dict[str, object]] | None:
    master = directory / "jrt0197_rule_master.jsonl"
    manifest = directory / "jrt0197_rule_manifest.json"
    if not master.is_file() or not manifest.is_file():
        return None
    return read_jsonl(master), {
        "baseline_type": "frozen",
        "baseline_id": directory.name,
        "baseline_hash": file_sha256(master),
        "manifest_hash": file_sha256(manifest),
    }


def diff_candidates(current: Sequence[RuleCandidate], runtime_root: Path) -> dict[str, object]:
    baseline = None
    frozen_root = runtime_root / "frozen"
    if frozen_root.is_dir():
        for directory in sorted((path for path in frozen_root.iterdir() if path.is_dir()), reverse=True):
            baseline = _frozen_baseline(directory)
            if baseline:
                break
    if baseline is None:
        candidate_root = runtime_root / "candidate"
        if candidate_root.is_dir():
            for directory in sorted((path for path in candidate_root.iterdir() if path.is_dir()), reverse=True):
                baseline = _candidate_baseline(directory)
                if baseline:
                    break
    current_map = {record.candidate_fingerprint: record for record in current}
    if baseline is None:
        return {
            "schema_name": "jrt0197_rule_diff",
            "schema_version": "1.0.0",
            "baseline_type": None,
            "baseline_status": "no_baseline",
            "baseline_id": None,
            "baseline_hash": None,
            "added_count": len(current),
            "removed_count": 0,
            "changed_count": 0,
            "added": [record.candidate_id for record in current],
            "removed": [],
            "changes": [],
            "record_count_change": len(current),
            "level_distribution_change": dict(Counter(str(record.minimum_security_level) for record in current)),
        }
    baseline_rows, metadata = baseline
    prior_by_fingerprint = {
        str(row.get("rule_fingerprint") or row.get("candidate_fingerprint")): row for row in baseline_rows
    }
    added = sorted(set(current_map) - set(prior_by_fingerprint))
    removed = sorted(set(prior_by_fingerprint) - set(current_map))
    current_levels = Counter(str(record.minimum_security_level) for record in current)
    prior_levels = Counter(str(row.get("minimum_security_level")) for row in baseline_rows)
    return {
        "schema_name": "jrt0197_rule_diff",
        "schema_version": "1.0.0",
        **metadata,
        "baseline_status": "compared",
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": 0,
        "added": [current_map[item].candidate_id for item in added],
        "removed": removed,
        "changes": [],
        "record_count_change": len(current) - len(baseline_rows),
        "level_distribution_change": {
            level: current_levels[level] - prior_levels[level] for level in sorted(current_levels | prior_levels)
        },
    }
