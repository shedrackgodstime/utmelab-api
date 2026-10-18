"""Authoritative syllabus catalog sync -- SQL lives here per the architecture rule.

The topic/subtopic taxonomy is not derived from questions and it is not
scraped from syllabus sites. It is stored in the production database, and a
bank that wants a stable ``subtopic_id`` to hand to ``ai-tag`` must read it
there read-only and land the rows in its own work lane. ``sync_catalog`` is
the one routine that owns that copy, so the only SQL is in this file.

Only read statements are used so a re-run can never mutate the production
source of truth.
"""

from __future__ import annotations

import json
from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository

__all__ = ["sync_catalog"]

# Production ships "order" (an SQLite keyword); the bank DDL stores the same
# column as "ord". Aliasing here keeps the insert list in the bank's shape.
TOPICS_SQL = """
SELECT slug, subject, exam, name, "order" AS ord, weight, objectives
FROM topics
ORDER BY "order" ASC
"""

SUBJECTS_SQL = """
SELECT slug, topic, name, "order" AS ord, objectives
FROM subtopics
ORDER BY "order" ASC
"""


# A production text column that may carry one trailing newline. The bank stores
# the same content as a JSON text column, so we normalise it to a tidy array.
def _normalise_objectives(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return json.dumps([str(item) for item in value])
    text = str(value or "").strip()
    return text if text else "[]"


async def _fetch(prod: Store, sql: str) -> list[dict[str, Any]]:
    return await prod.fetch_all(sql)


async def sync_catalog(prod: Store, repo: Repository) -> dict[str, int]:
    """Read the topic/subtopic catalog from ``prod`` and upsert it.

    The caller owns the store connection for the duration of the call.
    Returns how many rows were written for each logical table. Slugs are the
    primary key, so a second run is a no-op on rows that already exist.
    """
    topic_rows = await _fetch(prod, TOPICS_SQL)
    subtopic_rows = await _fetch(prod, SUBJECTS_SQL)

    now = now_iso()
    topics: list[dict[str, Any]] = []
    for row in topic_rows:
        topics.append(
            {
                "slug": str(row["slug"]),
                "subject": str(row["subject"]),
                "exam": str(row["exam"]),
                "name": str(row["name"]),
                "ord": int(row["ord"]),
                "weight": float(row["weight"]) if row["weight"] is not None else None,
                "objectives": _normalise_objectives(row["objectives"]),
                "created_at": now,
                "updated_at": now,
            }
        )

    written_topics = await repo.insert_many("topics", topics)

    subtopics: list[dict[str, Any]] = []
    for row in subtopic_rows:
        subtopics.append(
            {
                "slug": str(row["slug"]),
                "topic": str(row["topic"]),
                "name": str(row["name"]),
                "ord": int(row["ord"]),
                "objectives": _normalise_objectives(row["objectives"]),
                "created_at": now,
                "updated_at": now,
            }
        )

    written_subtopics = await repo.insert_many("subtopics", subtopics)

    return {
        "topics": written_topics,
        "subtopics": written_subtopics,
    }
