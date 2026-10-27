"""The production catalog, checked against the rules tagging depends on.

The tagging step can only choose a subtopic that exists and belongs to a
named topic. When the catalog breaks that contract the bank has nothing to
offer: a blank name is skipped, and a topic with no subtopics can never be
reached. Both defects cost rows silently, which is exactly the kind of thing
that should be visible before a batch runs, not after it stalls.

Everything here is a read. The repair is a catalog change, owned outside the
bank.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .db import Database

#: A topic or subtopic that cannot be offered to a model, with its location.
BLANK_TOPICS = """
SELECT exam, subject, slug
FROM topics
WHERE name IS NULL OR TRIM(name) = ''
ORDER BY exam, subject, slug
"""

BLANK_SUBTOPICS = """
SELECT t.exam, t.subject, s.slug
FROM subtopics s
JOIN topics t ON t.slug = s.topic
WHERE s.name IS NULL OR TRIM(s.name) = ''
ORDER BY t.exam, t.subject, s.slug
"""

ORPHANS = """
SELECT s.slug, s.topic
FROM subtopics s
WHERE NOT EXISTS (SELECT 1 FROM topics t WHERE t.slug = s.topic)
ORDER BY s.slug
"""

SUBJECTS_WITHOUT_TOPICS = """
SELECT s.exam, s.slug
FROM subjects s
WHERE NOT EXISTS (
    SELECT 1 FROM topics t WHERE t.exam = s.exam AND t.subject = s.slug
)
ORDER BY s.exam, s.slug
"""

TOPICS_WITHOUT_SUBTOPICS = """
SELECT t.exam, t.subject, COUNT(*) AS topics
FROM topics t
WHERE NOT EXISTS (SELECT 1 FROM subtopics s WHERE s.topic = t.slug)
GROUP BY t.exam, t.subject
ORDER BY topics DESC, t.exam, t.subject
"""

EXAM_COUNTS = """
SELECT s.exam, COUNT(DISTINCT s.slug) AS subjects,
       (SELECT COUNT(*) FROM topics t WHERE t.exam = s.exam) AS topics
FROM subjects s
GROUP BY s.exam
ORDER BY s.exam
"""

SUBTOPIC_COUNTS = """
SELECT t.exam, COUNT(*) AS subtopics
FROM subtopics s
JOIN topics t ON t.slug = s.topic
GROUP BY t.exam
"""


@dataclass(frozen=True)
class ExamCounts:
    """One exam's size in the catalog."""

    exam: str
    subjects: int
    topics: int
    subtopics: int


@dataclass(frozen=True)
class Defect:
    """One row that breaks the tagging contract."""

    exam: str
    subject: str
    slug: str


@dataclass(frozen=True)
class SubjectGap:
    """A subject whose topics are not all reachable by a subtopic."""

    exam: str
    subject: str
    topics: int


@dataclass(frozen=True)
class CatalogHealth:
    """What the catalog looks like, split by whether it costs a batch."""

    exams: tuple[ExamCounts, ...]
    parked: tuple[ExamCounts, ...]
    blank_topics: tuple[Defect, ...]
    blank_subtopics: tuple[Defect, ...]
    orphan_subtopics: tuple[Defect, ...]
    subjects_without_topics: tuple[Defect, ...]
    topics_without_subtopics: tuple[SubjectGap, ...]

    @property
    def errors(self) -> int:
        """Defects that make a row impossible to place."""
        return len(self.blank_topics) + len(self.blank_subtopics) + len(self.orphan_subtopics)

    @property
    def warnings(self) -> int:
        """Gaps that reduce the taggable surface."""
        return len(self.subjects_without_topics) + sum(
            gap.topics for gap in self.topics_without_subtopics
        )

    def ok(self, *, strict: bool = False) -> bool:
        """An error always fails; a gap fails only when ``strict`` is set."""
        if self.errors:
            return False
        return not strict or self.warnings == 0

    def as_dict(self) -> dict[str, Any]:
        """The same facts for a workflow."""
        return {
            "exams": [
                {
                    "exam": exam.exam,
                    "subjects": exam.subjects,
                    "topics": exam.topics,
                    "subtopics": exam.subtopics,
                }
                for exam in self.exams
            ],
            "parked": [{"exam": exam.exam, "subjects": exam.subjects} for exam in self.parked],
            "errors": {
                "blank_topics": [_defect(item) for item in self.blank_topics],
                "blank_subtopics": [_defect(item) for item in self.blank_subtopics],
                "orphan_subtopics": [
                    {"slug": item.slug, "topic": item.subject} for item in self.orphan_subtopics
                ],
                "count": self.errors,
            },
            "warnings": {
                "subjects_without_topics": [_defect(item) for item in self.subjects_without_topics],
                "topics_without_subtopics": [
                    {"exam": gap.exam, "subject": gap.subject, "topics": gap.topics}
                    for gap in self.topics_without_subtopics
                ],
                "count": self.warnings,
            },
            "ok": self.ok(),
        }


def _defect(item: Defect) -> dict[str, str]:
    return {"exam": item.exam, "subject": item.subject, "slug": item.slug}


async def check_catalog(database: Database) -> CatalogHealth:
    """Read the catalog and classify every defect it holds."""
    subjects = await database.query(EXAM_COUNTS)
    subtopics = {str(row[0]): int(row[1]) for row in (await database.query(SUBTOPIC_COUNTS)).rows}
    exams = tuple(
        ExamCounts(
            exam=str(row[0]),
            subjects=int(row[1]),
            topics=int(row[2]),
            subtopics=subtopics.get(str(row[0]), 0),
        )
        for row in subjects.rows
    )

    blank_topics = tuple(
        Defect(exam=str(row[0]), subject=str(row[1]), slug=str(row[2]))
        for row in (await database.query(BLANK_TOPICS)).rows
    )
    blank_subtopics = tuple(
        Defect(exam=str(row[0]), subject=str(row[1]), slug=str(row[2]))
        for row in (await database.query(BLANK_SUBTOPICS)).rows
    )
    # An orphan names a topic that is missing, so its location is the topic
    # slug itself; the exam and subject are unknown until someone fixes it.
    orphan_subtopics = tuple(
        Defect(exam="-", subject=str(row[1]), slug=str(row[0]))
        for row in (await database.query(ORPHANS)).rows
    )
    # An exam with no topics at all is parked, not broken: its catalog has not
    # been built yet, and every one of its subjects would otherwise be a
    # warning that never clears. A subject with no topics inside a live exam
    # stays a gap, because that subject can never be tagged.
    parked = tuple(exam for exam in exams if exam.topics == 0)
    parked_names = {exam.exam for exam in parked}
    subjects_without_topics = tuple(
        Defect(exam=str(row[0]), subject=str(row[1]), slug=str(row[1]))
        for row in (await database.query(SUBJECTS_WITHOUT_TOPICS)).rows
        if str(row[0]) not in parked_names
    )
    topics_without_subtopics = tuple(
        SubjectGap(exam=str(row[0]), subject=str(row[1]), topics=int(row[2]))
        for row in (await database.query(TOPICS_WITHOUT_SUBTOPICS)).rows
    )

    return CatalogHealth(
        exams=exams,
        parked=parked,
        blank_topics=blank_topics,
        blank_subtopics=blank_subtopics,
        orphan_subtopics=orphan_subtopics,
        subjects_without_topics=subjects_without_topics,
        topics_without_subtopics=topics_without_subtopics,
    )


__all__ = [
    "CatalogHealth",
    "Defect",
    "ExamCounts",
    "SubjectGap",
    "check_catalog",
]
