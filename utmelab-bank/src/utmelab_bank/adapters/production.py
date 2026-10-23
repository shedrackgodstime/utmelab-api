"""The production content reader. What the served bank already holds.

The catalog reader answers where a question goes. This one answers whether
the question is new, by reading the served bank's questions and computing
the keys the index holds.

The reader is the only place that knows how production stores a question.
The index only knows the keys.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Protocol

from utmelab_bank.domain.dedupe import (
    duplicate_content_key,
    duplicate_near_key,
    near_duplicate_fingerprint,
)
from utmelab_bank.domain.reports import Report


class SqlClient(Protocol):
    """Minimal async SQL client contract. The Turso client satisfies it."""

    async def execute(self, statement: str, args: list[Any] | None = None) -> Any: ...


class KnownQuestion:
    """One question production already holds, and its index keys.

    ``content_hash`` and ``near_duplicate`` are the keys the bank's index
    stores, not the raw fingerprints. Both carry the exam year, so the same
    question in two years is two entries and not a false duplicate.
    """

    __slots__ = ("question_id", "content_hash", "near_duplicate", "year")

    def __init__(
        self,
        question_id: str,
        content_hash: str,
        near_duplicate: str,
        year: int = 0,
    ) -> None:
        self.question_id = question_id
        self.content_hash = content_hash
        self.near_duplicate = near_duplicate
        self.year = year

    def __repr__(self) -> str:
        return f"KnownQuestion({self.question_id!r}, {self.year}, {self.content_hash!r})"


def _image_keys(raw_inline: object) -> list[str]:
    """Image anchors from one production inline array."""
    if not isinstance(raw_inline, list):
        return []
    keys: list[str] = []
    for entry in raw_inline:
        if not isinstance(entry, dict) or entry.get("kind") != "image":
            continue
        keys.append(f"{entry.get('url')}|{entry.get('position') or ''}|{entry.get('alt') or ''}")
    return keys


def _option_images(options: object) -> list[str]:
    if not isinstance(options, list):
        return []
    keys: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        text = option.get("text")
        if not isinstance(text, dict):
            continue
        keys.extend(_image_keys(text.get("inline")))
    return keys


#: How many rows one production read asks for.
#:
#: The served database is reached over one HTTP stream per query. A single
#: read of every question carries all of the text and options, and a stream
#: that runs for four minutes is closed by the server with a 404 before it
#: finishes. A page is small enough to complete, and the keyset keeps the
#: cost of the page independent of how far into the table it is.
PAGE = 100

#: A page of questions, cursor style. ``id`` is unique and the order is the
#: primary key's, so a page starts after the last id it saw.
_PAGE_SQL = (
    "SELECT id, year, content_hash, text, inline, options FROM questions "
    "WHERE id > ? ORDER BY id LIMIT ?"
)


class ProductionContentReader:
    """Reads the served bank's questions and computes their index keys.

    The content hash is read, not recomputed, because production stores the
    one it wrote and that is the value the serving predicate compares. The
    near-duplicate fingerprint has to be computed, because production does
    not store it. Both are then qualified with the row's year.
    """

    def __init__(self, client: SqlClient) -> None:
        self._client = client

    async def known(self) -> tuple[KnownQuestion, ...]:
        """Every question production holds, with both index keys."""
        return tuple([known async for known in self.iter_known()])

    def _known(self, row: tuple[Any, ...]) -> KnownQuestion:
        question_id = str(row[0])
        year = int(row[1])
        content_hash = str(row[2])
        stem = str(row[3])
        stem_inline = json.loads(row[4]) if row[4] else []
        options = json.loads(row[5]) if row[5] else []
        texts = tuple(str(option.get("text", {}).get("text", "")) for option in options)
        images = [
            *_image_keys(stem_inline),
            *_option_images(options),
        ]
        near = near_duplicate_fingerprint(stem, texts, tuple(images))
        return KnownQuestion(
            question_id=question_id,
            content_hash=duplicate_content_key(content_hash, year),
            near_duplicate=duplicate_near_key(near, year),
            year=year,
        )

    async def iter_known(self) -> AsyncIterator[KnownQuestion]:
        """The same set, one page at a time.

        A page is a complete query, not a stream that has to stay open for
        the whole bank. The caller can collect the result before it drops the
        old index, so a failed read never leaves the bank with no index.
        """
        cursor = ""
        while True:
            result = await self._client.execute(_PAGE_SQL, [cursor, PAGE])
            rows = result.rows
            if not rows:
                return
            for row in rows:
                yield self._known(row)
            cursor = str(rows[-1][0])
            if len(rows) < PAGE:
                return

    async def hashes(self) -> dict[str, str]:
        """Every question id production holds, and the hash it holds.

        This is what the drift check compares against. The hash is read, not
        recomputed, because production stores the one it wrote.
        """
        result = await self._client.execute("SELECT id, content_hash FROM questions")
        return {str(row[0]): str(row[1]) for row in result.rows}

    async def question_ids(self, *, exam: str, subject: str, year: int) -> frozenset[str]:
        """Question IDs already held for one scrape scope."""
        result = await self._client.execute(
            "SELECT id FROM questions WHERE exam = ? AND subject = ? AND year = ?",
            [exam, subject, year],
        )
        return frozenset(str(row[0]) for row in result.rows)


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
            created_at = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
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
