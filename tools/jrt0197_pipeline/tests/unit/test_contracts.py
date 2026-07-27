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

from jrt_pipeline.contracts import canonical_json_bytes, object_schema, read_jsonl, write_jsonl


def test_jsonl_is_byte_deterministic(tmp_path: Path) -> None:
    left, right = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    records = [{"文本": "客户", "level": 3, "note": None}]
    schema = object_schema(["文本", "level", "note"])
    assert write_jsonl(left, records, schema) == write_jsonl(right, records, schema)
    assert left.read_bytes() == right.read_bytes()
    assert left.read_bytes().endswith(b"\n")
    assert read_jsonl(left) == records


def test_schema_key_order_is_preserved_in_bytes() -> None:
    schema = object_schema(["instruction", "input", "output"])
    value = {"output": "o", "input": "i", "instruction": "x"}
    assert canonical_json_bytes(value, schema) == b'{"instruction":"x","input":"i","output":"o"}\n'
