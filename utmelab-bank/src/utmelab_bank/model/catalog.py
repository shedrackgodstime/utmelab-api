"""The catalog: exams, subjects, topics, subtopics.

These are scraped from the syllabus sites rather than derived from questions,
so they get no ``raw_`` lane. A syllabus page is cheap to refetch and
deterministic to reparse, and keeping the source verbatim buys nothing here.
"""

from __future__ import annotations

from utmelab_bank.model.base import BankModel, Timed

__all__ = ["Exam", "Subject", "Topic", "Subtopic", "TopicCountry"]


class Exam(BankModel):
    """An examination sitting. ``countries`` is a comma list because the API
    stores it as one text column."""

    code: str
    name: str
    countries: str = "NG"
    status: str = "active"
    has_full_paper: bool = False
    subjects_required: int | None = None
    duration_minutes: int | None = None
    rules: dict[str, object] | None = None


class Subject(BankModel):
    """A subject within an exam, keyed by the slug the API routes on."""

    slug: str
    exam: str
    name: str
    is_compulsory: bool = False
    objective_paper_questions: int | None = None


class Topic(BankModel):
    """A topic within a subject."""

    slug: str
    subject: str
    exam: str
    name: str
    order: int = 0
    weight: float | None = None
    objectives: list[str] = []


class Subtopic(Timed):
    """A subtopic within a topic. Keyed by slug, because questions point at it."""

    slug: str
    topic: str
    name: str
    order: int = 0
    objectives: list[str] = []


class TopicCountry(BankModel):
    """Which countries a topic applies to. Empty means every country."""

    topic: str
    country: str
