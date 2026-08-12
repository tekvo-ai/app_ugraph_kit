from __future__ import annotations

from pathlib import Path

import pytest

from ugraph.config import Config


@pytest.fixture()
def kb(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    (root / "raw").mkdir(parents=True)
    return root


@pytest.fixture()
def cfg(kb: Path) -> Config:
    return Config(kb=kb)
