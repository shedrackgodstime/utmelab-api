"""The catalog rows a rebuilt syllabus becomes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SLUG_LIMIT = 60


def slugify(text: str, limit: int = SLUG_LIMIT) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(text) > limit:
        text = text[:limit].rstrip("-")
    return text or "topic"


class Slugger:
    """Keep slugs unique without losing the name that produced them."""

    def __init__(self, taken: set[str] | None = None) -> None:
        self._taken = set(taken or ())

    def make(self, name: str, hint: str) -> str:
        slug = f"waec-{slugify(name)}"
        if slug not in self._taken:
            self._taken.add(slug)
            return slug
        candidate = f"{slug}-{slugify(hint)}"
        if candidate not in self._taken:
            self._taken.add(candidate)
            return candidate
        for suffix in range(2, 1000):
            candidate = f"{slug}-{suffix}"
            if candidate not in self._taken:
                self._taken.add(candidate)
                return candidate
        raise RuntimeError(f"cannot make a unique slug from {name!r}")


@dataclass(slots=True)
class Subtopic:
    name: str
    order: int


@dataclass(slots=True)
class Topic:
    name: str
    order: int
    subtopics: list[Subtopic] = field(default_factory=list)


@dataclass(slots=True)
class Syllabus:
    subject: str
    display: str
    topics: list[Topic]

    def rows(
        self, taken: set[str] | None = None, hint: str = ""
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Topic and subtopic rows in the catalog's stored shape."""
        slugger = Slugger(taken)
        topic_rows: list[dict[str, Any]] = []
        subtopic_rows: list[dict[str, Any]] = []
        for topic in self.topics:
            topic_slug = slugger.make(topic.name, hint or self.subject)
            topic_rows.append(
                {
                    "slug": topic_slug,
                    "subject": self.subject,
                    "exam": "WAEC",
                    "name": topic.name,
                    "order": topic.order,
                    "weight": 0,
                    "objectives": [],
                    "countries": [],
                }
            )
            for subtopic in topic.subtopics:
                subtopic_rows.append(
                    {
                        "slug": slugger.make(subtopic.name, hint or self.subject),
                        "topic": topic_slug,
                        "name": subtopic.name,
                        "order": subtopic.order,
                        "objectives": [],
                    }
                )
        return topic_rows, subtopic_rows


__all__ = ["Slugger", "Subtopic", "Syllabus", "Topic", "slugify"]
