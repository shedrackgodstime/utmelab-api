"""The content index. What the bank already knows about.

Two fingerprints for every question the bank knows: the content hash, which
never collides, and the near-duplicate fingerprint, which catches the
reworded copy. Both are kept here so a duplicate check is a lookup.

The index holds two origins. ``production`` is what the served bank already
holds, and ``bank`` is what the bank has produced itself. Both are checked,
because a row that duplicates one the bank produced is just as much of a
waste of effort as one that duplicates a live row.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from utmelab_bank.domain.dedupe import Duplicate

#: Where a known question came from.
PRODUCTION = "production"
BANK = "bank"

#: How many rows one statement carries.
#:
#: The round trip to Turso is about a second from where the bank runs, so
#: one write per row would take an hour for a bank of two thousand. The
#: engine takes four thousand parameters, so five hundred rows is safe, and
#: one statement per five hundred rows turns an hour into a minute.
BATCH = 500


class ContentIndexStore:
    """Reads and writes the bank's index of what it already holds."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def remember(
        self,
        *,
        content_hash: str,
        near_duplicate: str,
        origin: str,
        question_id: str,
    ) -> None:
        """Record one known question."""
        await self._client.execute(
            """
            INSERT OR REPLACE INTO content_index (
                content_hash, near_duplicate, origin, question_id
            ) VALUES (?, ?, ?, ?)
            """,
            [content_hash, near_duplicate, origin, question_id],
        )

    async def remember_many(
        self,
        entries: Sequence[tuple[str, str, str, str]],
        *,
        commit: bool = True,
    ) -> None:
        """Record many known questions, one statement per batch.

        The entries are ``(content_hash, near_duplicate, origin, question_id)``.

        With ``commit=False`` the writes stay open and the caller commits
        them together, which is what a bulk load wants, because a commit is
        a round trip.
        """
        for start in range(0, len(entries), BATCH):
            batch = entries[start : start + BATCH]
            placeholders = ", ".join("(?, ?, ?, ?)" for _ in batch)
            args: list[Any] = []
            for content_hash, near_duplicate, origin, question_id in batch:
                args.extend([content_hash, near_duplicate, origin, question_id])
            await self._client.execute(
                f"INSERT OR REPLACE INTO content_index VALUES {placeholders}",
                args,
                commit=commit,
            )

    async def forget(self, origin: str) -> None:
        """Drop everything from one origin, so it can be reloaded clean."""
        await self._client.execute("DELETE FROM content_index WHERE origin = ?", [origin])

    async def forget_question(self, question_id: str, *, origin: str = BANK) -> None:
        """Drop one question's entries from one origin.

        A capture moves an image inline from the source url to the stored
        name, which changes the content hash and the near key. The old entry
        has to go before the new content is checked, both so the row cannot
        match itself and so a crash between the upload and the re-index can
        be repaired by running the capture again.
        """
        await self._client.execute(
            "DELETE FROM content_index WHERE origin = ? AND question_id = ?",
            [origin, question_id],
        )

    async def exact_match(self, content_hash: str) -> str | None:
        """The id of the known question with this content hash, if any."""
        result = await self._client.execute(
            "SELECT question_id FROM content_index WHERE content_hash = ? LIMIT 1",
            [content_hash],
        )
        return str(result.rows[0][0]) if result.rows else None

    async def near_matches(self, near_duplicate: str) -> tuple[str, ...]:
        """The ids of the known questions with this near-duplicate fingerprint."""
        result = await self._client.execute(
            "SELECT question_id FROM content_index WHERE near_duplicate = ? ORDER BY question_id",
            [near_duplicate],
        )
        return tuple(str(row[0]) for row in result.rows)

    async def find(self, *, content_hash: str, near_duplicate: str) -> Duplicate | None:
        """The first duplicate of this content, exact first, in one query.

        The exact match wins, because a row that is the same content is a
        stronger finding than one that is a reworded copy, and a reviewer
        should be told the stronger thing first. Asking for both in one
        statement matters on a scrape: two queries per row is a round trip
        the bank does not need to spend.
        """
        result = await self._client.execute(
            """
            SELECT question_id, content_hash
            FROM content_index
            WHERE content_hash = ? OR near_duplicate = ?
            ORDER BY CASE WHEN content_hash = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            [content_hash, near_duplicate, content_hash],
        )
        if not result.rows:
            return None
        row = result.rows[0]
        kind = "exact" if str(row[1]) == content_hash else "near"
        return Duplicate(kind=kind, question_id=str(row[0]))

    async def commit(self) -> None:
        """Commit whatever is open, so a batch of writes lands together."""
        await self._client.commit()

    async def count(self, origin: str | None = None) -> int:
        """How many questions the index holds."""
        if origin is None:
            result = await self._client.execute("SELECT count(*) FROM content_index")
        else:
            result = await self._client.execute(
                "SELECT count(*) FROM content_index WHERE origin = ?", [origin]
            )
        return int(result.rows[0][0])


__all__ = ["BANK", "BATCH", "PRODUCTION", "ContentIndexStore"]
