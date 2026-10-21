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
from typing import Any, Optional, Protocol

from utmelab_bank.domain.dedupe import near_duplicate_fingerprint


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


__all__ = ["KnownQuestion", "ProductionContentReader", "SqlClient"]
