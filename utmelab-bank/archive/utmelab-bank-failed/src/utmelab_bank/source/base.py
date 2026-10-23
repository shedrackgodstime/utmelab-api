"""What a source is.

A source answers one question: where does raw material come from. It does not
decide what is good, and it never writes anything beyond the raw lane.

The pipeline had three harvesters that were the same 200 lines with a different
exam string, and two of them disagreed about whether a cloze stem was usable.
Here a source declares what it can fetch and how, and the parsing lives in one
place.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from utmelab_bank.config import Config
from utmelab_bank.model.question import Question

__all__ = ["FetchRequest", "Source", "SourceCapabilities"]


class SourceCapabilities:
    """What a source can produce. Read by ``utmelab-bank sources``."""

    def __init__(
        self,
        *,
        name: str,
        exams: tuple[str, ...],
        subjects: tuple[str, ...] = (),
        media: bool = False,
        note: str = "",
    ) -> None:
        self.name = name
        self.exams = exams
        self.subjects = subjects
        self.media = media
        self.note = note


class FetchRequest:
    """What to fetch. Validated by the source, not by the caller."""

    def __init__(
        self,
        *,
        exam: str,
        subject: str,
        year: int | None = None,
        limit: int | None = None,
        pages: int | None = None,
        delay: float | None = None,
    ) -> None:
        self.exam = exam
        self.subject = subject
        self.year = year
        self.limit = limit
        self.pages = pages
        self.delay = delay

    def __repr__(self) -> str:
        return (
            f"FetchRequest(exam={self.exam!r}, subject={self.subject!r}, "
            f"year={self.year!r}, limit={self.limit!r})"
        )


@runtime_checkable
class Source(Protocol):
    """A place question material comes from.

    The protocol stays narrow: a source fetches questions, nothing else.
    """

    name: str

    def capabilities(self) -> SourceCapabilities:
        """What this source covers. Read by the registry and by ``sources``."""
        ...

    def supports(self, request: FetchRequest) -> bool:
        """Whether this source can serve the request at all."""
        ...

    async def scrape(self, request: FetchRequest, config: Config) -> list[Question]:
        """Fetch questions. Raises rather than returning partial garbage."""
        ...
