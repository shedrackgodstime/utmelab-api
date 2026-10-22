"""The subject map, read from one data file.

The map is the source's own vocabulary. A production catalog slug goes in and
the site's slug comes out, and a missing entry is a refusal rather than a
slugified guess. Guessing is how ``use-of-english`` once became a request for
a page that does not exist.

One direction only. The reverse exists as ``catalog_slug`` and the parser does
not call it: matching either side of a pair would make two different subjects
interchangeable.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, NamedTuple

from .errors import SourceError

__all__ = [
    "ExamSubjects",
    "SubjectEntry",
    "SubjectMap",
    "known_exams",
    "load_map",
    "profile_subjects",
    "subjects_for",
]

MAP_PATH: Final[Path] = Path(__file__).with_name("subjects.json")


class SubjectEntry(NamedTuple):
    """One subject, in both of the names it has."""

    source: str
    slug: str
    name: str


class ExamSubjects(NamedTuple):
    display: str
    default_year: int
    subjects: tuple[SubjectEntry, ...]

    @property
    def by_source(self) -> dict[str, SubjectEntry]:
        return {entry.source: entry for entry in self.subjects}

    @property
    def by_slug(self) -> dict[str, SubjectEntry]:
        return {entry.slug: entry for entry in self.subjects}

    def slugs(self) -> tuple[str, ...]:
        return tuple(entry.slug for entry in self.subjects)


class SubjectMap(NamedTuple):
    exams: dict[str, ExamSubjects]
    skipped: tuple[dict[str, str], ...]

    def exam(self, code: str) -> ExamSubjects:
        found = self.exams.get(code.lower())
        if found is None:
            raise SourceError(
                "no subjects are mapped for that exam",
                exam=code,
                known=sorted(self.exams),
            )
        return found

    def source_slug(self, exam: str, subject: str) -> str:
        """The site's slug for a catalog subject.

        Raises when the subject is not in the map. A fallback here would
        quietly request a page that does not exist, which is the failure this
        file exists to prevent.
        """
        subjects = self.exam(exam)
        entry = subjects.by_slug.get(subject) or subjects.by_source.get(subject)
        if entry is None:
            raise SourceError(
                "that subject is not in the map, and a guess would be a decision nobody made",
                exam=exam,
                subject=subject,
                hint="add it to subjects.json",
                known=list(subjects.slugs())[:8],
            )
        return entry.source

    def catalog_slug(self, exam: str, source: str) -> str:
        subjects = self.exam(exam)
        entry = subjects.by_source.get(source)
        if entry is None:
            raise SourceError(
                "that source slug is not in the map",
                exam=exam,
                source=source,
                hint="add it to subjects.json",
            )
        return entry.slug


@lru_cache(maxsize=1)
def load_map() -> SubjectMap:
    """Read the map once. It is read per run and never changes within one."""
    if not MAP_PATH.is_file():
        raise SourceError("the subject map is missing", path=str(MAP_PATH))
    raw: dict[str, Any] = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    exams: dict[str, ExamSubjects] = {}
    for code, block in raw.get("exams", {}).items():
        exams[code.lower()] = ExamSubjects(
            display=str(block.get("display", code.upper())),
            default_year=int(block.get("default_year", 2025)),
            subjects=tuple(
                SubjectEntry(
                    source=str(entry["source"]),
                    slug=str(entry["slug"]),
                    name=str(entry.get("name", entry["slug"])),
                )
                for entry in block.get("subjects", [])
            ),
        )

    if not exams:
        raise SourceError("the subject map has no exams", path=str(MAP_PATH))

    skipped = tuple(
        {"source": str(entry["source"]), "reason": str(entry.get("reason", ""))}
        for entry in raw.get("skipped", [])
    )
    return SubjectMap(exams=exams, skipped=skipped)


def subjects_for(exam: str) -> ExamSubjects:
    return load_map().exam(exam)


def known_exams() -> tuple[str, ...]:
    """The exams this source carries papers for."""
    return tuple(sorted(load_map().exams))


def profile_subjects() -> dict[str, str]:
    """The JAMB catalog slugs and their display names.

    The profile describes a source, and myschool serves three exams from one
    subject vocabulary. JAMB is the one the catalog spends the most on, so it
    is the map the profile advertises; a WAEC run still resolves through the
    exam the scope names.
    """
    jamb = load_map().exam("jamb")
    return {entry.slug: entry.name for entry in jamb.subjects}
