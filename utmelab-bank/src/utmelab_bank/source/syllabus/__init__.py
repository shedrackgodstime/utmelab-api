"""Catalog sources: the syllabus sites.

Subjects, topics and subtopics come from here rather than from a question page,
which is why the catalog gets no ``raw_`` lane. A syllabus page is cheap to
refetch and deterministic to reparse.
"""

from __future__ import annotations

from typing import Final

from utmelab_bank.config import Config
from utmelab_bank.errors import SourceError
from utmelab_bank.model.catalog import Subject, Subtopic, Topic
from utmelab_bank.source.base import FetchRequest, SourceCapabilities
from utmelab_bank.source.http import PoliteSession
from utmelab_bank.text import slugify, strip_tags, visible_lines

__all__ = ["SyllabusSource", "jambsyllabus", "waecsyllabus"]

_BASE: Final[str] = "https://jambsyllabus.com"


class SyllabusSource:
    """Topics and subtopics from one syllabus site.

    The two importers that did this job were the same function pasted twice with
    a different entity table, and the WAEC copy's entity table had six
    identity no-ops in it because the names had already been unescaped when the
    file was written. One implementation, and entities are decoded exactly once.
    """

    def __init__(
        self,
        *,
        name: str,
        base: str,
        exam: str,
        api_path: str | None = None,
    ) -> None:
        self.name = name
        self._base = base
        self._exam = exam
        self._api_path = api_path

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            name=self.name,
            exams=(self._exam,),
            catalog=True,
            media=False,
            note="topic tree",
        )

    def supports(self, request: FetchRequest) -> bool:
        return request.exam == self._exam

    async def scrape(self, request: FetchRequest, config: Config) -> list[Subject]:
        """Not what this source is for. Use ``catalog``."""
        raise SourceError("this source fetches the catalog, not questions", source=self.name)

    async def catalog(self, subject: str, config: Config) -> tuple[Subject, list[Topic], list[Subtopic]]:
        """One subject's topic tree."""
        async with PoliteSession(config) as session:
            markup = (await session.get(self._url(subject))).text
        return self.parse(markup, subject=subject)

    def _url(self, subject: str) -> str:
        if self._api_path is None:
            return f"{self._base}/{slugify(subject)}"
        return f"{self._base}{self._api_path.format(slug=slugify(subject))}"

    def parse(
        self,
        markup: str,
        *,
        subject: str,
    ) -> tuple[Subject, list[Topic], list[Subtopic]]:
        """Turn a syllabus page into a subject with its topics and subtopics.

        The topic heading is a line ending in a colon or matching a topic
        pattern, and subtopics are the indented items under it. Neither the
        header level nor the indentation is reliable across the two sites, so
        both are used and the topic is whichever signal appeared last.
        """
        lines = visible_lines(markup)
        topics: list[Topic] = []
        subtopics: list[Subtopic] = []
        current: str | None = None
        order = 0

        for raw in lines:
            line = strip_tags(raw).rstrip()
            if not line:
                continue
            is_item = line[:2].isdigit() or line.startswith(("-", "*"))
            body = line.lstrip("-* ").strip()

            if is_item and current is not None:
                subtopics.append(
                    Subtopic(
                        slug=slugify(body),
                        topic=current,
                        name=body,
                        order=len(subtopics) + 1,
                    )
                )
                continue

            if body.endswith(":") or _looks_like_topic(body):
                current = slugify(body)
                order += 1
                topics.append(
                    Topic(
                        slug=current,
                        subject=slugify(subject),
                        exam=self._exam,
                        name=body.rstrip(":"),
                        order=order,
                    )
                )

        return (
            Subject(slug=slugify(subject), exam=self._exam, name=subject),
            topics,
            subtopics,
        )


def _looks_like_topic(line: str) -> bool:
    """A short heading with no sentence punctuation in it."""
    if len(line) > 90 or line.endswith((".", "?", "!")):
        return False
    words = line.split()
    return 1 <= len(words) <= 8


jambsyllabus = SyllabusSource(
    name="jambsyllabus",
    base=_BASE,
    exam="jamb",
)

waecsyllabus = SyllabusSource(
    name="waecsyllabus",
    base="https://waecsyllabus.com",
    exam="waec",
    api_path="/{slug}",
)
