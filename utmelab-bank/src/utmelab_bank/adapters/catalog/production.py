"""Production catalog reader. The production DB is the only authority for topics."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional, Protocol

from utmelab_bank.domain.models import (
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
)


class SqlClient(Protocol):
    """Minimal async SQL client contract. The Turso client satisfies it."""

    async def execute(self, statement: str, args: Optional[list[Any]] = None) -> Any: ...


class ProductionCatalogReader:
    """Reads topics, subtopics and objectives for one exam and subject."""

    def __init__(self, client: SqlClient) -> None:
        self._client = client

    async def snapshot(self, exam: str, subject: str) -> CatalogSnapshot:
        """Build a versioned catalog snapshot for one exam and subject."""
        subject_row = await self._subject(exam, subject)
        if subject_row is None:
            raise LookupError(f"no subject {subject!r} for exam {exam!r}")

        topics = await self._topics(exam, subject)
        subtopics = await self._subtopics(topics)

        return CatalogSnapshot(
            version=self._version(exam, subject, topics, subtopics),
            exam=exam,
            subject=subject,
            topics=topics,
            subtopics=subtopics,
        )

    async def _subject(self, exam: str, subject: str) -> Optional[tuple[str, str, str]]:
        result = await self._client.execute(
            "SELECT slug, exam, name FROM subjects WHERE exam = ? AND slug = ?",
            [exam, subject],
        )
        rows = result.rows
        if not rows:
            return None
        return (str(rows[0][0]), str(rows[0][1]), str(rows[0][2]))

    async def _topics(self, exam: str, subject: str) -> tuple[CatalogTopic, ...]:
        result = await self._client.execute(
            'SELECT slug, name, objectives FROM topics WHERE exam = ? AND subject = ? ORDER BY "order"',
            [exam, subject],
        )
        topics: list[CatalogTopic] = []
        for row in result.rows:
            topics.append(
                CatalogTopic(
                    id=str(row[0]),
                    slug=str(row[0]),
                    name=str(row[1]),
                    objectives=_objectives(row[2]),
                )
            )
        return tuple(topics)

    async def _subtopics(self, topics: tuple[CatalogTopic, ...]) -> tuple[CatalogSubtopic, ...]:
        if not topics:
            return ()
        slugs = [topic.id for topic in topics]
        placeholders = ", ".join("?" for _ in slugs)
        result = await self._client.execute(
            f'SELECT slug, topic, name, objectives FROM subtopics WHERE topic IN ({placeholders}) ORDER BY "order"',
            slugs,
        )
        subtopics: list[CatalogSubtopic] = []
        for row in result.rows:
            subtopics.append(
                CatalogSubtopic(
                    id=str(row[0]),
                    slug=str(row[0]),
                    name=str(row[2]),
                    topic_id=str(row[1]),
                    objectives=_objectives(row[3]),
                )
            )
        return tuple(subtopics)

    def _version(
        self,
        exam: str,
        subject: str,
        topics: tuple[CatalogTopic, ...],
        subtopics: tuple[CatalogSubtopic, ...],
    ) -> str:
        """A stable version string that changes when the catalog changes."""
        parts = [exam, subject]
        parts.extend(f"{topic.id}:{topic.name}" for topic in topics)
        parts.extend(f"{subtopic.id}:{subtopic.topic_id}" for subtopic in subtopics)
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
        return f"sha256:{digest[:16]}"


def _objectives(value: Any) -> tuple[str, ...]:
    """Read the objectives column, which is a JSON array of strings."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed)
