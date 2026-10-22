"""pytest configuration: make ``import utmetag`` work from any cwd, plus fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2]  # .../tools
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from helpers import make_bank  # noqa: E402


@pytest.fixture
def bank() -> dict:
    return make_bank()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    bank = make_bank()
    for name in ("questions", "subjects", "topics", "subtopics", "passages", "verifications"):
        (tmp_path / f"{name}.json").write_text(json.dumps(bank[name]))
    return tmp_path
