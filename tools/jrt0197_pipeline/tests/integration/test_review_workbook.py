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

import openpyxl
import pytest

from jrt_pipeline.review.contract import WorkbookRuntime, invoke_workbook_builder


@pytest.mark.skipif(not os.getenv("JRT0197_NODE_MODULES"), reason="bundled workbook runtime not configured")
def test_builds_review_workbook_and_all_previews(tmp_path: Path) -> None:
    contract = {
        "schema_name": "jrt0197_review_contract",
        "schema_version": "1.0.0",
        "run_id": "synthetic",
        "diagnostic_only": False,
        "editable_columns": ["review_decision", "review_comment", "reviewer", "reviewed_at"],
        "metadata": {
            "run_id": "synthetic",
            "candidate_jsonl_sha256": "sha256:a",
            "manifest_sha256": "sha256:b",
            "review_schema_version": "1.0.0",
            "editable_columns": ["review_decision", "review_comment", "reviewer", "reviewed_at"],
            "candidate_id_count": 1,
            "candidate_id_set_hash": "sha256:c",
        },
        "records": [
            {
                "candidate_id": "CAND-A1-0001",
                "source_order": 1,
                "source_physical_page": 17,
                "class1": "客户",
                "class2": "个人",
                "class2_definition": "定义",
                "class3": "个人自然信息",
                "class3_definition": "定义",
                "class4": "个人基本概况信息",
                "class4_description": "姓名等",
                "minimum_security_level": 3,
                "note": None,
                "raw_extraction": "{}",
                "normalized_content": "{}",
                "inheritance_trace": "[]",
                "candidate_fingerprint": "sha256:test",
                "validation_flags": "[]",
                "review_decision": None,
                "review_comment": None,
                "reviewer": None,
                "reviewed_at": None,
            }
        ],
        "findings": [],
        "diff": {
            "baseline_status": "no_baseline",
            "added_count": 1,
            "removed_count": 0,
            "changed_count": 0,
            "added": ["CAND-A1-0001"],
            "removed": [],
            "changes": [],
        },
        "statistics": {
            "record_count": 1,
            "level_distribution": {"3": 1},
            "error_count": 0,
            "warning_count": 0,
            "info_count": 0,
        },
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
    workbook = tmp_path / "review.xlsx"
    previews = tmp_path / "previews" / "workbook"
    runtime = WorkbookRuntime.from_environment()
    invoke_workbook_builder(contract_path, workbook, previews, runtime)
    book = openpyxl.load_workbook(workbook)
    assert book.sheetnames == [
        "审核说明",
        "候选规则",
        "自动校验问题",
        "差异对照",
        "统计汇总",
        "候选清单",
        "__review_metadata",
    ]
    assert book["__review_metadata"].sheet_state == "hidden"
    assert book["__review_metadata"].protection.sheet
    assert book["候选规则"].freeze_panes == "A2"
    assert len(list(previews.glob("*.png"))) == 6
