"""The production content reader. What the served bank already holds.

The catalog reader answers where a question goes. This one answers whether
the question is new, by reading the served bank's questions and computing
the two fingerprints the index holds.

The reader is the only place that knows how production stores a question.
The index only knows the fingerprints.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Optional, Protocol

from utmelab_bank.domain.dedupe import near_duplicate_fingerprint
from utmelab_bank.domain.reports import Report


class SqlClient(Protocol):
    """Minimal async SQL client contract. The Turso client satisfies it."""

    async def execute(self, statement: str, args: Optional[list[Any]] = None) -> Any: ...


class KnownQuestion:
    """One question production already holds, and its two fingerprints."""

    __slots__ = ("question_id", "content_hash", "near_duplicate")

    def __init__(
        self, question_id: str, content_hash: str, near_duplicate: str
    ) -> None:
        self.question_id = question_id
        self.content_hash = content_hash
        self.near_duplicate = near_duplicate

    def __repr__(self) -> str:
        return f"KnownQuestion({self.question_id!r}, {self.content_hash!r})"


class ProductionContentReader:
    """Reads the served bank's questions and computes their fingerprints.

    The content hash is read, not recomputed, because production stores the
    one it wrote and that is the value the serving predicate compares. The
    near-duplicate fingerprint has to be computed, because production does
    not store it.
    """

    def __init__(self, client: SqlClient) -> None:
        self._client = client

    async def known(self) -> tuple[KnownQuestion, ...]:
        """Every question production holds, with both fingerprints."""
        result = await self._client.execute(
            "SELECT id, content_hash, text, options FROM questions"
        )
        return tuple(self._known(row) for row in result.rows)

    def _known(self, row: tuple[Any, ...]) -> KnownQuestion:
        question_id = str(row[0])
        content_hash = str(row[1])
        stem = str(row[2])
        options = json.loads(row[3]) if row[3] else []
        texts = tuple(
            str(option.get("text", {}).get("text", "")) for option in options
        )
        return KnownQuestion(
            question_id=question_id,
            content_hash=content_hash,
            near_duplicate=near_duplicate_fingerprint(stem, texts),
        )

    async def iter_known(self) -> AsyncIterator[KnownQuestion]:
        """The same set, one at a time, for a caller that streams it.

        The refresh writes each question to the index as it goes, so the
        memory stays flat however big the bank gets.
        """
        result = await self._client.execute(
            "SELECT id, content_hash, text, options FROM questions"
        )
        for row in result.rows:
            yield self._known(row)

    async def hashes(self) -> dict[str, str]:
        """Every question id production holds, and the hash it holds.

        This is what the drift check compares against. The hash is read, not
        recomputed, because production stores the one it wrote.
        """
        result = await self._client.execute("SELECT id, content_hash FROM questions")
        return {str(row[0]): str(row[1]) for row in result.rows}


class ProductionReportReader:
    """Reads the reports consumers have made.

    The server owns the table, and the reasons are its five. The bank reads
    them and turns them into work.
    """

    def __init__(self, client: SqlClient) -> None:
        self._client = client

    async def reports(self) -> tuple[Report, ...]:
        """Every report the server holds, oldest first."""
        result = await self._client.execute(
            "SELECT id, target_type, target_id, reporter, reason, detail, "
            "created_at FROM reports ORDER BY created_at, id"
        )
        return tuple(self._report(row) for row in result.rows)

    def _report(self, row: tuple[Any, ...]) -> Report:
        created = row[6]
        if isinstance(created, (int, float)):
            created_at = datetime.fromtimestamp(created, tz=UTC)
        else:
            created_at = datetime.fromisoformat(str(created).replace("Z", "++00:00"))
        return Report(
            id=str(row[0]),
            target_type=str(row[1]),
            target_id=str(row[2]),
            reporter=str(row[3]),
            reason=str(row[4]),
            detail=str(row[5]) if row[5] is not None else None,
            created_at=created_at,
        )


__all__ = [
    "KnownQuestion",
    "ProductionContentReader",
    "ProductionReportReader",
    "SqlClient",
]
