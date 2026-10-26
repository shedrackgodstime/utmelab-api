"""Production catalog reader. The production DB is the only authority for topics."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Protocol

from utmelab_bank.domain.models import (
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
)

_log = logging.getLogger(__name__)


class SqlClient(Protocol):
    """Minimal async SQL client contract. The Turso client satisfies it."""

    async def execute(self, statement: str, args: list[Any] | None = None) -> Any: ...


class ProductionCatalogReader:
    """Reads topics, subtopics and objectives for one exam and subject."""

    def __init__(self, client: SqlClient) -> None:
        self._client = client

    async def snapshot(
        self, exam: str, subject: str, country: str | None = None
    ) -> CatalogSnapshot:
        """Build a versioned catalog snapshot for one exam and subject."""
        subject_row = await self._subject(exam, subject)
        if subject_row is None:
            raise LookupError(f"no subject {subject!r} for exam {exam!r}")
        subject_countries = subject_row[3]
        if country and subject_countries and country.upper() not in subject_countries:
            raise LookupError(
                f"subject {subject!r} for exam {exam!r} is not available in {country.upper()}"
            )

        topics = await self._topics(exam, subject, country)
        subtopics = await self._subtopics(topics)
        topic_ids = {topic.id for topic in topics}
        dangling = sorted(
            subtopic.id for subtopic in subtopics if subtopic.topic_id not in topic_ids
        )
        if dangling:
            raise LookupError(
                f"catalog {exam}/{subject} has subtopics with missing topics: "
                f"{', '.join(dangling[:5])}"
            )

        return CatalogSnapshot(
            version=self._version(exam, subject, country, topics, subtopics),
            exam=exam,
            subject=subject,
            country=country.upper() if country else None,
            topics=topics,
            subtopics=subtopics,
        )

    async def _subject(
        self, exam: str, subject: str
    ) -> tuple[str, str, str, tuple[str, ...]] | None:
        result = await self._client.execute(
            "SELECT slug, exam, name, countries FROM subjects WHERE exam = ? AND slug = ?",
            [exam, subject],
        )
        rows = result.rows
        if not rows:
            return None
        row = rows[0]
        return (str(row[0]), str(row[1]), str(row[2]), _countries(row[3] if len(row) > 3 else None))

    async def _topics(
        self, exam: str, subject: str, country: str | None
    ) -> tuple[CatalogTopic, ...]:
        query = (
            "SELECT slug, name, objectives, countries "
            "FROM topics WHERE exam = ? AND subject = ? "
            'ORDER BY "order"'
        )
        result = await self._client.execute(query, [exam, subject])
        topics: list[CatalogTopic] = []
        unnamed: list[str] = []
        for row in result.rows:
            countries = _countries(row[3] if len(row) > 3 else None)
            if country and countries and country.upper() not in countries:
                continue
            name = "" if row[1] is None else str(row[1]).strip()
            if not name:
                # A topic with no name cannot be offered to a model as a
                # choice. Skipping it keeps the rest of the subject usable;
                # the warning keeps the production defect visible.
                unnamed.append(str(row[0]))
                continue
            topics.append(
                CatalogTopic(
                    id=str(row[0]),
                    slug=str(row[0]),
                    name=name,
                    objectives=_objectives(row[2]),
                    countries=countries,
                )
            )
        if unnamed:
            _log.warning(
                "catalog %s/%s has %d unnamed topic(s), skipped: %s",
                exam,
                subject,
                len(unnamed),
                ", ".join(unnamed[:5]),
            )
        return tuple(topics)

    async def _subtopics(self, topics: tuple[CatalogTopic, ...]) -> tuple[CatalogSubtopic, ...]:
        if not topics:
            return ()
        slugs = [topic.id for topic in topics]
        placeholders = ", ".join("?" for _ in slugs)
        query = (
            f"SELECT slug, topic, name, objectives "
            f'FROM subtopics WHERE topic IN ({placeholders}) ORDER BY "order"'
        )
        result = await self._client.execute(query, slugs)
        subtopics: list[CatalogSubtopic] = []
        unnamed: list[str] = []
        for row in result.rows:
            name = "" if row[2] is None else str(row[2]).strip()
            if not name:
                unnamed.append(str(row[0]))
                continue
            subtopics.append(
                CatalogSubtopic(
                    id=str(row[0]),
                    slug=str(row[0]),
                    name=name,
                    topic_id=str(row[1]),
                    objectives=_objectives(row[3]),
                )
            )
        if unnamed:
            _log.warning(
                "catalog has %d unnamed subtopic(s), skipped: %s",
                len(unnamed),
                ", ".join(unnamed[:5]),
            )
        return tuple(subtopics)

    def _version(
        self,
        exam: str,
        subject: str,
        country: str | None,
        topics: tuple[CatalogTopic, ...],
        subtopics: tuple[CatalogSubtopic, ...],
    ) -> str:
        """A stable version string that changes when the catalog changes."""
        parts = [exam, subject, country.upper() if country else ""]
        parts.extend(f"{topic.id}:{topic.name}:{','.join(topic.countries)}" for topic in topics)
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
    except TypeError, ValueError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed)


def _countries(value: Any) -> tuple[str, ...]:
    """Read a production country scope, with empty meaning universal."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        parsed = value
    else:
        try:
            parsed = json.loads(str(value))
        except TypeError, ValueError:
            return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item).upper() for item in parsed if str(item).strip())
