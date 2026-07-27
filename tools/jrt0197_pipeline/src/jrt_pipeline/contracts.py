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
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from .hashing import file_sha256, sha256_bytes

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


class ContractOrderError(ValueError):
    pass


def object_schema(key_order: list[str] | tuple[str, ...]) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "x-key-order": list(key_order),
        "properties": {key: {} for key in key_order},
        "additionalProperties": False,
    }


def canonicalize_by_schema(value: object, schema: Mapping[str, object]) -> object:
    if isinstance(value, Mapping):
        order = tuple(schema.get("x-key-order", value.keys()))
        unknown = set(value) - set(order)
        if unknown:
            raise ContractOrderError(f"undeclared keys: {sorted(unknown)}")
        properties = schema.get("properties", {})
        return {key: canonicalize_by_schema(value[key], properties.get(key, {})) for key in order if key in value}
    if isinstance(value, list):
        item_schema = schema.get("items", {})
        return [canonicalize_by_schema(item, item_schema) for item in value]
    return value


def canonical_json_bytes(value: object, schema: Mapping[str, object]) -> bytes:
    ordered = canonicalize_by_schema(value, schema)
    text = json.dumps(ordered, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


def write_json(path: Path, value: Mapping[str, object], schema: Mapping[str, object]) -> str:
    jsonschema.Draft202012Validator(schema).validate(value)
    payload = canonical_json_bytes(value, schema)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def write_jsonl(path: Path, records: list[Mapping[str, object]], schema: Mapping[str, object]) -> str:
    validator = jsonschema.Draft202012Validator(schema)
    payload_parts: list[bytes] = []
    for record in records:
        validator.validate(record)
        payload_parts.append(canonical_json_bytes(record, schema))
    payload = b"".join(payload_parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def read_json(path: Path, schema: Mapping[str, object] | None = None) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if schema is not None:
        jsonschema.Draft202012Validator(schema).validate(value)
    return value


def read_jsonl(path: Path, schema: Mapping[str, object] | None = None) -> list[dict[str, object]]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if schema is not None:
        validator = jsonschema.Draft202012Validator(schema)
        for record in records:
            validator.validate(record)
    return records


def load_schema(schema_name: str) -> dict[str, object]:
    filename = schema_name if schema_name.endswith(".schema.json") else f"{schema_name}.schema.json"
    return read_json(SCHEMA_DIR / filename)


def validate_schema(value: object, schema_name: str) -> None:
    jsonschema.Draft202012Validator(load_schema(schema_name)).validate(value)


def _mapping(value: object) -> dict[str, object]:
    return asdict(value)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SourceFragment:
    physical_page: int
    row_locator: str
    bounding_boxes: list[list[float]] = field(default_factory=list)
    block_ids: list[str] = field(default_factory=list)
    raw_cells_sha256: str = ""

    def to_mapping(self) -> dict[str, object]:
        return _mapping(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SourceFragment:
        return cls(**value)


@dataclass(frozen=True)
class OwnedBlock:
    block_id: str
    text: str
    bounding_box: list[float]
    ownership: str
    in_table_body: bool
    row_locator: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return _mapping(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> OwnedBlock:
        return cls(**value)


@dataclass(frozen=True)
class PageEvidence:
    physical_page: int
    width: float
    height: float
    page_png_sha256: str
    table_bounds: list[float] | None
    raw_cells: list[dict[str, object]]
    raw_cells_sha256: str
    cell_bounding_boxes: list[list[float]]
    blocks: list[OwnedBlock]
    unassigned_count: int
    page_png_source: str | None = None
    page_png_bytes: bytes = field(default=b"", repr=False, compare=False)

    def to_mapping(self) -> dict[str, object]:
        value = _mapping(self)
        value.pop("page_png_bytes", None)
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PageEvidence:
        converted = dict(value)
        converted["blocks"] = [OwnedBlock.from_mapping(block) for block in converted["blocks"]]
        return cls(**converted)


@dataclass(frozen=True)
class RuleCandidate:
    candidate_id: str
    source_order: int
    source_fragments: list[SourceFragment]
    source_physical_page_start: int
    source_physical_page_end: int
    source_physical_page: int
    source_row_locator: str
    raw_extraction: dict[str, object]
    normalized_content: dict[str, object]
    inheritance_trace: list[dict[str, object]]
    class1: str | None
    class2: str | None
    class2_definition: str | None
    class3: str | None
    class3_definition: str | None
    class4: str | None
    class4_description: str | None
    minimum_security_level: int | None
    minimum_security_level_raw: str | int | None
    minimum_security_level_parse_status: str
    note: str | None
    path_depth: int
    source_structure_status: str
    validation_flags: list[str]
    source_fragments_sha256: str
    candidate_fingerprint: str

    def to_mapping(self) -> dict[str, object]:
        return _mapping(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RuleCandidate:
        converted = dict(value)
        converted["source_fragments"] = [SourceFragment.from_mapping(item) for item in converted["source_fragments"]]
        return cls(**converted)


@dataclass(frozen=True)
class CandidateManifest:
    schema_name: str
    schema_version: str
    artifact_id: str
    run_id: str
    pipeline_state: str
    source_pdf_sha256: str
    candidate_jsonl_sha256: str
    page_evidence_jsonl_sha256: str
    page_png_set_sha256: str
    page_count: int
    ownership_block_count: int
    unassigned_block_count: int
    extraction_version: str
    normalization_version: str
    fingerprint_version: str
    tool_versions: dict[str, str]
    physical_page_start: int
    physical_page_end: int
    record_count: int
    level_distribution: dict[str, int]
    comparison_baseline: dict[str, object]
    validation_status: str
    parent_artifact_id: str | None = None
    parent_artifact_manifest_sha256: str | None = None
    workbook_sha256: str | None = None
    preview_count: int = 0

    def to_mapping(self) -> dict[str, object]:
        return _mapping(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CandidateManifest:
        return cls(**value)


def write_run_metadata(path: Path, **values: object) -> str:
    generated_at = values.pop("generated_at", None)
    if generated_at is None:
        epoch = os.getenv("SOURCE_DATE_EPOCH")
        generated_at = int(epoch) if epoch else None
    payload = {"generated_at": generated_at, **values}
    return write_json(path, payload, object_schema(list(payload)))


def verify_named_manifest(path: Path, expected_schema: str) -> dict[str, object]:
    value = read_json(path)
    if value.get("schema_name") != expected_schema:
        raise ValueError(f"unexpected manifest schema: {value.get('schema_name')!r}")
    return value


__all__ = [
    "CandidateManifest",
    "OwnedBlock",
    "PageEvidence",
    "RuleCandidate",
    "SourceFragment",
    "canonical_json_bytes",
    "file_sha256",
    "load_schema",
    "object_schema",
    "read_json",
    "read_jsonl",
    "validate_schema",
    "verify_named_manifest",
    "write_json",
    "write_jsonl",
    "write_run_metadata",
]
