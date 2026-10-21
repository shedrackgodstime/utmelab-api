"""Source adapters. One package per origin, and one place to choose one."""

from __future__ import annotations

from pathlib import Path

from utmelab_bank.config import BANK_ROOT, ConfigError
from utmelab_bank.domain.ports import Source

from .fixture import FixtureSource
from .myschool import MyschoolSource

#: Where the recorded fixture lives when the caller does not name a directory.
#: Only the source tree has it; a deployment must pass its own source.
DEFAULT_FIXTURE_DIR = BANK_ROOT / "tests" / "fixtures" / "sources" / "fixture"

#: Every source the runner knows how to build.
KNOWN_SOURCES = ("fixture", "myschool")


def create_source(name: str, *, fixture_dir: Path | str | None = None) -> Source:
    """Build a source by name.

    The runner never imports a source directly, so adding one is one branch
    here and one package beside the fixture. A name the runner does not know
    is a configuration error, not a silent no-op.
    """
    if name == "fixture":
        return FixtureSource(fixture_dir or DEFAULT_FIXTURE_DIR)
    if name == "myschool":
        return MyschoolSource()
    known = ", ".join(KNOWN_SOURCES)
    raise ConfigError(f"unknown source {name!r}; known sources: {known}")


__all__ = ["DEFAULT_FIXTURE_DIR", "KNOWN_SOURCES", "create_source"]
