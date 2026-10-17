"""myschool.ng. One site, three exams.

``utmelab-bank scrape --source myschool --exam jamb --subject physics --year 2025``

The exam is an argument, not a source, because the site serves all three from
one place and the previous three harvesters were this file three times over.
"""

from __future__ import annotations

from utmelab_bank.config import Config
from utmelab_bank.errors import SourceError
from utmelab_bank.model.question import Question
from utmelab_bank.source.base import FetchRequest, SourceCapabilities
from utmelab_bank.source.http import PoliteSession
from utmelab_bank.source.myschool.parser import (
    EXAMS,
    ParsedQuestion,
    api_last_page,
    listing_url,
    parse_detail,
    parse_listing,
    slug_for,
)

__all__ = ["MyschoolSource", "NAME", "NAME_JSON"]

NAME = "myschool"
NAME_JSON = "myschool-json"


class MyschoolSource:
    """Questions from myschool.ng over html, or over its json api.

    Two fetch strategies, one parser. WAEC is served by a json endpoint the html
    listing does not cover, which is why the old WAEC harvester was a separate
    255 line file with its own copy of the text handling and its own idea of
    which subject a row belonged to.
    """

    name = NAME

    def __init__(self, *, strategy: str = "api", name: str = NAME) -> None:
        self._strategy = strategy
        self.name = name

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            name=self.name,
            exams=tuple(EXAMS),
            catalog=False,
            media=True,
            note=f"{self._strategy} strategy",
        )

    def supports(self, request: FetchRequest) -> bool:
        return request.exam in EXAMS

    async def scrape(self, request: FetchRequest, config: Config) -> list[Question]:
        """Fetch one subject's questions for one exam.

        Goes through :func:`utmelab_bank.source.myschool.run.fetch_subject`, which
        is where the paging, the delay and the raw-lane write live. Split out so
        this class stays a declaration of what the source is.
        """
        from utmelab_bank.source.myschool.run import fetch_subject

        if not self.supports(request):
            raise SourceError(
                "this source does not serve that exam",
                source=self.name,
                exam=request.exam,
                serves=self.capabilities().exams,
            )
        parsed: list[ParsedQuestion] = await fetch_subject(
            request,
            config,
            strategy=self._strategy,
        )
        return [item.question for item in parsed]

    async def probe(self, request: FetchRequest, config: Config) -> int:
        """Count what is on offer, without fetching a single question.

        The nightly check that answers "is there anything new" for the cost of
        one request, which matters because the api serves five rows a page: the
        whole count comes from ``last_page``.
        """
        async with PoliteSession(config) as session:
            spec = EXAMS[request.exam]
            year = request.year or spec.default_year
            slug = slug_for(request.exam, request.subject)
            payload = await session.get_json(listing_url(request.exam, slug, year))

        pages = api_last_page(payload)
        data = payload.get("data")
        practice = data.get("practice_questions") if isinstance(data, dict) else None
        per_page = int(practice.get("per_page", 5)) if isinstance(practice, dict) else 5
        total = pages * per_page
        return total if request.limit is None else min(total, request.limit)
