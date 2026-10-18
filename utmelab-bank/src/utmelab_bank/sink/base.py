"""Where rows land, and the guard that stops them landing in the wrong place.

The invariant this package must never break is that no JSON file is ever written
into the repository. The pipeline and ``tools/`` both violated it, and the
result was a 3.1 MB bank in git and scripts whose data contract pointed at a
path that no longer existed.

So persistence goes through :class:`Sink`, and :mod:`utmelab_bank.sink.json` is
the only implementation allowed to touch the filesystem. Its one legal path is
under ``var/``, which the repository already ignores, and it refuses any other.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["Sink", "WriteIntent"]


class WriteIntent(Protocol):
    """What a sink is being asked to persist."""

    logical: str
    rows: list[dict[str, object]]


@runtime_checkable
class Sink(Protocol):
    """A destination for rows.

    A task never opens a file or builds a statement. It hands a sink rows and
    gets back whether they landed, which is what makes ``--sink json`` a real
    development mode rather than a second code path through every task.
    """

    name: str

    async def write(self, logical: str, rows: list[dict[str, object]]) -> int:
        """Persist rows. Returns how many were written."""
        ...

    async def read(self, logical: str, where: str = "all") -> list[dict[str, object]]:
        """Read rows back, using the same selector vocabulary as the database."""
        ...

    async def close(self) -> None: ...
