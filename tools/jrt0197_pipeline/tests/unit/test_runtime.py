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

import pytest

from jrt_pipeline.runtime import ArtifactExistsError, atomic_artifact_dir


def test_atomic_artifact_dir_rejects_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "candidate" / "run-1"
    target.mkdir(parents=True)
    with pytest.raises(ArtifactExistsError), atomic_artifact_dir(target):
        pass


def test_atomic_artifact_dir_publishes_sibling_directory(tmp_path: Path) -> None:
    target = tmp_path / "candidate" / "run-2"
    with atomic_artifact_dir(target) as staging:
        (staging / "proof.txt").write_text("ok\n", encoding="utf-8", newline="\n")
    assert (target / "proof.txt").read_bytes() == b"ok\n"
    assert not (target.parent / ".tmp-run-2").exists()
