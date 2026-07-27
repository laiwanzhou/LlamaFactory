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
from pathlib import Path

from jrt_pipeline.review.contract import EDITABLE_COLUMNS, build_review_contract


def test_review_contract_contains_only_python_decisions(tmp_path: Path) -> None:
    candidate = {
        "candidate_id": "CAND-A1-0001",
        "source_order": 1,
        "class1": "客户",
        "class2": "个人",
        "class2_definition": "定义",
        "class3": "个人自然信息",
        "class3_definition": "定义",
        "class4": "个人基本概况信息",
        "class4_description": "姓名等",
        "minimum_security_level": 3,
        "note": None,
        "source_physical_page": 17,
        "source_physical_page_start": 17,
        "source_physical_page_end": 17,
        "source_row_locator": "table_0:row_3",
        "raw_extraction": {},
        "normalized_content": {},
        "inheritance_trace": [],
        "candidate_fingerprint": "sha256:test",
        "validation_flags": [],
    }
    (tmp_path / "jrt0197_rule_master_candidate.jsonl").write_text(
        json.dumps(candidate, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    (tmp_path / "jrt0197_rule_validation_report.json").write_text(
        json.dumps(
            {
                "validation_status": "passed",
                "error_count": 0,
                "warning_count": 0,
                "info_count": 0,
                "findings": [],
                "record_count": 1,
                "level_distribution": {"3": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "jrt0197_rule_diff.json").write_text(
        json.dumps(
            {
                "baseline_status": "no_baseline",
                "added_count": 1,
                "removed_count": 0,
                "changed_count": 0,
                "added": ["CAND-A1-0001"],
                "removed": [],
                "changes": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "jrt0197_rule_candidate_manifest.json").write_text(
        json.dumps({"run_id": "synthetic", "pipeline_state": "validated"}), encoding="utf-8"
    )
    contract = build_review_contract(tmp_path)
    assert contract["editable_columns"] == list(EDITABLE_COLUMNS)
    assert contract["records"][0]["class4"] == "个人基本概况信息"
    assert contract["metadata"]["candidate_id_count"] == 1
    assert contract["metadata"]["candidate_jsonl_sha256"].startswith("sha256:")
