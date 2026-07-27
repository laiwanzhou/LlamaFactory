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

import re
from dataclasses import dataclass

PUNCTUATION_MAP = str.maketrans({"，": ",", "；": ";", "：": ":", "（": "(", "）": ")"})
CHINESE_LEVELS = {"一级": 1, "二级": 2, "三级": 3, "四级": 4, "五级": 5}


@dataclass(frozen=True)
class ParsedLevel:
    raw: str | int | None
    value: int | None
    status: str


def normalize_rule_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s*\n\s*", "", value.strip())
    normalized = re.sub(r"[ \t\r\f\v]+", " ", normalized).translate(PUNCTUATION_MAP)
    return normalized or None


def parse_level(value: str | int | None) -> ParsedLevel:
    if value is None or value == "":
        return ParsedLevel(value, None, "missing")
    if isinstance(value, int):
        return ParsedLevel(value, value, "parsed")
    text = normalize_rule_text(value) or ""
    if text in CHINESE_LEVELS:
        return ParsedLevel(value, CHINESE_LEVELS[text], "parsed")
    match = re.fullmatch(r"(?:Level\s*)?([0-9]+)(?:级)?", text, re.IGNORECASE)
    if match:
        return ParsedLevel(value, int(match.group(1)), "parsed")
    return ParsedLevel(value, None, "unparseable")
