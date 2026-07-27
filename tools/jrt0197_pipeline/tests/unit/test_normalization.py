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

import pytest

from jrt_pipeline.normalization import normalize_rule_text, parse_level


def test_normalization_changes_layout_not_words() -> None:
    assert normalize_rule_text(" 交易\n 金额，信息 ") == "交易金额,信息"
    assert normalize_rule_text("疑似错别字") == "疑似错别字"


@pytest.mark.parametrize(
    ("raw", "value", "status"),
    [("3级", 3, "parsed"), ("三级", 3, "parsed"), ("Level 4", 4, "parsed"), ("?", None, "unparseable")],
)
def test_parse_level_preserves_status(raw: str, value: int | None, status: str) -> None:
    parsed = parse_level(raw)
    assert parsed.raw == raw
    assert parsed.value == value
    assert parsed.status == status
