"""The subject map, read from one file.

The archive had this in ``config/harvest.json`` and the Rust importer said why
it lived in a file rather than a constant:

    The subject map lives in config/harvest.json, not here. It used to be a
    ``const`` in this file, with the harvester holding a second copy in Python.
    Two lists is how a subject gets crawled under one slug and merged under
    another, which is exactly how art/fine-arts and
    accounts-principles-of-accounts/principles-of-accounts drifted apart. One
    file, read by both. A missing entry is a refusal, never a fallback.

That file was deleted in ``fc6f1a0``, along with the crawler that read it, and
the map that survived inside the pipeline was an identity map missing eleven
subjects. So it is recovered here from ``fc6f1a0^:config/harvest.json`` and from
``tools/import_waec_inbox.py``, and it is a data file again.

The refusal is the part that matters. An unmapped subject is a decision for a
person, so it raises rather than falling back to a slugified guess. Guessing is
how ``use-of-english`` became a request for a page that does not exist, which
is how the largest subject in the bank became unreachable.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, NamedTuple

from utmelab_bank.errors import SourceError

__all__ = ["SubjectMap", "SubjectEntry", "ExamSubjects", "load_map", "EXAMS", "subjects_for"]

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
    """Every exam's subjects, plus the ones deliberately not harvested."""

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

        Raises when the subject is not in the map. A fallback here would quietly
        request a page that does not exist, which is the failure this whole file
        exists to prevent.
        """
        subjects = self.exam(exam)
        entry = subjects.by_slug.get(subject) or subjects.by_source.get(subject)
        if entry is None:
            raise SourceError(
                "that subject is not in the map, and a guess would be a decision "
                "nobody made",
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
def load_map(path: Path | None = None) -> SubjectMap:
    """Read the map once. Cached because it is read per request and never changes
    within a run."""
    target = path or MAP_PATH
    if not target.is_file():
        raise SourceError("the subject map is missing", path=str(target))
    raw: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))

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
        raise SourceError("the subject map has no exams", path=str(target))

    skipped = tuple(
        {"source": str(entry["source"]), "reason": str(entry.get("reason", ""))}
        for entry in raw.get("skipped", [])
    )
    return SubjectMap(exams=exams, skipped=skipped)


def subjects_for(exam: str) -> ExamSubjects:
    return load_map().exam(exam)


def EXAMS() -> tuple[str, ...]:
    """The exams this source carries papers for."""
    return tuple(sorted(load_map().exams))
