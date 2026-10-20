"""Production reference data, read-only.

The bank does not own the syllabus. This is the only module that reads
production reference rows: topics, subtopics, subjects, and the content hashes
of questions already served. Passages are not here: they are bank content and
are read from the bank's own lane (see ``task.passage``).

Every query is cached for the life of the run. ``ai-tag`` asks for one
subject's subtopics, not the whole catalogue, so the cost is one read per
subject instead of one read per question.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol

from utmelab_bank.store.client import Store

if TYPE_CHECKING:
    from utmelab_bank.config import Config

__all__ = ["Reference", "ReferenceReader"]


class ReferenceReader(Protocol):
    """What a task needs from production. Tests may stand in for it."""

    async def topics_and_subtopics(
        self, subject: str, exam: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...

    async def subtopic(self, slug: str) -> dict[str, Any] | None: ...

    async def topic(self, slug: str) -> dict[str, Any] | None: ...

    async def subject(self, slug: str, exam: str) -> dict[str, Any] | None: ...

    async def has_content_hash(self, digest: str) -> bool: ...

    async def aclose(self) -> None: ...


_SUBTOPICS_SQL = """
SELECT s.slug AS subtopic_slug,
       s.name AS subtopic_name,
       s.objectives AS subtopic_objectives,
       t.slug AS topic_slug,
       t.name AS topic_name,
       t.objectives AS topic_objectives,
       t.subject AS subject,
       t.exam AS exam
FROM subtopics s
JOIN topics t ON t.slug = s.topic
WHERE lower(t.subject) = lower(:subject)
  AND lower(t.exam) = lower(:exam)
ORDER BY t."order" ASC, s."order" ASC
"""

_SUBTOPIC_SQL = """
SELECT s.slug AS slug,
       s.topic AS topic,
       s.name AS name,
       s.objectives AS objectives,
       t.subject AS subject,
       t.exam AS exam
FROM subtopics s
JOIN topics t ON t.slug = s.topic
WHERE s.slug = :slug
"""

_TOPIC_SQL = """
SELECT slug, subject, exam, name, "order" AS ord, weight, objectives
FROM topics
WHERE slug = :slug
"""

_SUBJECT_SQL = """
SELECT slug, exam, name, is_compulsory, objective_paper_questions
FROM subjects
WHERE lower(slug) = lower(:slug) AND lower(exam) = lower(:exam)
"""

_HASHES_SQL = """
SELECT content_hash FROM questions
WHERE content_hash IS NOT NULL AND content_hash <> ''
"""


def _objectives(value: Any) -> list[str]:
    """A production objectives column as a list of strings."""
    if isinstance(value, list | tuple):
        return [str(item) for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        return [text]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item or "").strip()]
    return [str(parsed)]


class Reference:
    """A read-only view of the production database."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._subtopics: dict[
            tuple[str, str], tuple[list[dict[str, Any]], list[dict[str, Any]]]
        ] = {}
        self._subtopic_cache: dict[str, dict[str, Any] | None] = {}
        self._subjects: dict[tuple[str, str], dict[str, Any] | None] = {}
        self._hashes: set[str] | None = None

    @classmethod
    async def open(cls, config: Config) -> Reference:
        """Open production with the read-only credential.

        The store refuses writes, and the credential is itself read-only, so a
        caller cannot turn this into a writer by mistake.
        """
        store = await Store.open(
            config.require_prod(),
            config.prod_database_token,
            read_only=True,
        )
        return cls(store)

    async def aclose(self) -> None:
        await self._store.aclose()

    async def topics_and_subtopics(
        self, subject: str, exam: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The subtopics and topics for one subject and exam, prompt-shaped."""
        key = (subject.strip().casefold(), exam.strip().casefold())
        cached = self._subtopics.get(key)
        if cached is not None:
            return cached

        rows = await self._store.fetch_all(
            _SUBTOPICS_SQL,
            {"subject": subject, "exam": exam},
        )
        topics_by_slug: dict[str, dict[str, Any]] = {}
        subtopics: list[dict[str, Any]] = []
        for row in rows:
            topic_slug = str(row["topic_slug"])
            topics_by_slug.setdefault(
                topic_slug,
                {
                    "slug": topic_slug,
                    "name": str(row["topic_name"]),
                    "subject": str(row["subject"]),
                    "exam": str(row["exam"]),
                    "objectives": _objectives(row.get("topic_objectives")),
                },
            )
            subtopics.append(
                {
                    "slug": str(row["subtopic_slug"]),
                    "topic": topic_slug,
                    "name": str(row["subtopic_name"]),
                    "objectives": _objectives(row.get("subtopic_objectives")),
                }
            )

        result = (subtopics, list(topics_by_slug.values()))
        self._subtopics[key] = result
        return result

    async def subtopic(self, slug: str) -> dict[str, Any] | None:
        if slug in self._subtopic_cache:
            return self._subtopic_cache[slug]
        row = await self._store.fetch_one(_SUBTOPIC_SQL, {"slug": slug})
        if row is not None:
            row["objectives"] = _objectives(row.get("objectives"))
        self._subtopic_cache[slug] = row
        return row

    async def topic(self, slug: str) -> dict[str, Any] | None:
        row = await self._store.fetch_one(_TOPIC_SQL, {"slug": slug})
        if row is not None:
            row["objectives"] = _objectives(row.get("objectives"))
        return row

    async def subject(self, slug: str, exam: str) -> dict[str, Any] | None:
        key = (slug.strip().casefold(), exam.strip().casefold())
        if key in self._subjects:
            return self._subjects[key]
        row = await self._store.fetch_one(_SUBJECT_SQL, {"slug": slug, "exam": exam})
        self._subjects[key] = row
        return row

    async def has_content_hash(self, digest: str) -> bool:
        """Whether production already serves this exact content."""
        if not digest:
            return False
        if self._hashes is None:
            rows = await self._store.fetch_all(_HASHES_SQL)
            self._hashes = {str(row["content_hash"]) for row in rows}
        return digest in self._hashes
