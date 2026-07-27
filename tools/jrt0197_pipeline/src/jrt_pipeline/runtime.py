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

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class ArtifactExistsError(FileExistsError):
    pass


class CrossVolumePublishError(OSError):
    pass


@contextmanager
def atomic_artifact_dir(target: Path) -> Iterator[Path]:
    target = target.resolve()
    if target.exists():
        raise ArtifactExistsError(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".tmp-{target.name}"
    if staging.exists():
        raise ArtifactExistsError(str(staging))
    staging.mkdir()
    try:
        yield staging
        if staging.drive.casefold() != target.drive.casefold():
            raise CrossVolumePublishError(str(target))
        staging.replace(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
