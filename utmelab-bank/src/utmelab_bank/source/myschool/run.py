"""The fetch loop for myschool, kept out of the source class.

A source declares what it is. The loop that walks a listing, spaces its
requests, parses each row and hands back parsed questions is machinery, and
machinery belongs somewhere both fetch strategies can share.

Two strategies, because the site has two:

``api``
    ``/api/web/v1/classroom/{subject}``. This is the listing. The html page
    carries no question links at all, and the api is explicit about the correct
    option, the exam and the year, none of which the html makes you infer.

``html``
    ``/classroom/{subject}/{id}``. Kept because a question's own markup can be
    richer than the api's copy, and because it is what the earlier harvesters
    proved works. Not the listing.
"""

from __future__ import annotations

import logging
from typing import Final

from utmelab_bank.config import Config
from utmelab_bank.errors import SourceError
from utmelab_bank.source.base import FetchRequest
from utmelab_bank.source.http import PoliteSession
from utmelab_bank.source.myschool.parser import (
    EXAMS,
    JsonRow,
    ParsedQuestion,
    api_last_page,
    listing_url,
    parse_api_listing,
    parse_api_question,
    parse_detail,
    parse_listing,
    slug_for,
    subject_listing_url,
)

__all__ = ["fetch_subject", "fetch_via_api", "fetch_via_html", "DETAIL_URL"]

log = logging.getLogger(__name__)

_BASE: Final[str] = "https://myschool.ng"
DETAIL_URL: Final[str] = _BASE + "/classroom/{slug}/{item_id}?exam_type={exam}&exam_year={year}"

async def fetch_subject(
    request: FetchRequest,
    config: Config,
    *,
    strategy: str = "api",
    on_item: object = None,
) -> list[ParsedQuestion]:
    """Fetch a subject's questions by whichever strategy the source declares."""
    if strategy == "html":
        return await fetch_via_html(request, config, on_item=on_item)
    return await fetch_via_api(request, config, on_item=on_item)


async def fetch_via_api(
    request: FetchRequest,
    config: Config,
    *,
    on_item: object = None,
) -> list[ParsedQuestion]:
    """Walk the api's pages and parse each row.

    The api serves five rows a page and ignores any page size we ask for, so a
    hundred question paper costs twenty requests. The session holds the delay,
    which is the only reason this is polite rather than a nuisance.
    """
    spec = _spec(request)
    year = request.year or spec.default_year
    slug = slug_for(request.exam, request.subject)

    parsed: list[ParsedQuestion] = []
    refused: dict[str, int] = {}
    page = 1
    max_pages = request.pages or 0

    async with PoliteSession(config, delay=request.delay) as session:
        while True:
            payload = await session.get_json(listing_url(request.exam, slug, year, page))
            rows = parse_api_listing(payload)
            if not rows:
                break

            for row in rows:
                try:
                    parsed.append(
                        parse_api_question(
                            row,
                            exam=request.exam,
                            subject=request.subject,
                            year=year,
                        )
                    )
                except SourceError as error:
                    key = error.detail
                    refused[key] = refused.get(key, 0) + 1
                    continue
                if request.limit and len(parsed) >= request.limit:
                    return _report(parsed, refused)

            if callable(on_item):
                on_item(page, api_last_page(payload))
            if page >= api_last_page(payload):
                break
            if max_pages and page >= max_pages:
                break
            page += 1

    return _report(parsed, refused)


def _report(parsed: list[ParsedQuestion], refused: dict[str, int]) -> list[ParsedQuestion]:
    """Log what was refused and why, then hand back what parsed.

    The old harvesters printed their refusals nowhere, so a run that lost a
    third of a paper looked exactly like a run where the paper was short.
    """
    if refused:
        for reason, count in sorted(refused.items(), key=lambda pair: -pair[1]):
            log.warning("refused %d rows: %s", count, reason)
    return parsed


async def fetch_via_html(
    request: FetchRequest,
    config: Config,
    *,
    on_item: object = None,
) -> list[ParsedQuestion]:
    """Walk the html listing. Kept for parity with the earlier harvesters."""
    year = request.year or _spec(request).default_year
    slug = slug_for(request.exam, request.subject)

    parsed: list[ParsedQuestion] = []
    refused: dict[str, int] = {}
    items: list[tuple[str, str]] = []
    page = 1
    max_pages = request.pages or 1

    async with PoliteSession(config, delay=request.delay) as session:
        # Walk the subject listing. The exam root carries navigation and no
        # question links, which is why the api is the listing elsewhere.
        while page <= max_pages:
            listing = await session.get(subject_listing_url(request.exam, slug, year, page))
            found = parse_listing(listing.text)
            if not found:
                break
            seen = {item_id for _, item_id in items}
            items.extend(pair for pair in found if pair[1] not in seen)
            if request.limit and len(items) >= request.limit:
                items = items[: request.limit]
                break
            page += 1

        for index, (item_slug, item_id) in enumerate(items, start=1):
            detail_url = DETAIL_URL.format(
                slug=item_slug or slug,
                item_id=item_id,
                exam=request.exam,
                year=year,
            )
            try:
                page = await session.get(detail_url)
                parsed.append(
                    parse_detail(
                        page.text,
                        exam=request.exam,
                        subject=request.subject,
                        year=year,
                        slug=item_slug or slug,
                        item_id=item_id,
                    )
                )
            except SourceError as error:
                refused[error.detail] = refused.get(error.detail, 0) + 1
                continue
            if callable(on_item):
                on_item(index, len(items))

    return _report(parsed, refused)


def _spec(request: FetchRequest) -> object:
    spec = EXAMS.get(request.exam)
    if spec is None:
        raise SourceError("unknown exam", exam=request.exam, known=sorted(EXMAS))
    return spec


def rows_of(parsed: list[ParsedQuestion]) -> list[JsonRow]:
    """The raw rows behind a parsed list, for a caller that wants provenance."""
    return [JsonRow({"id": item.source_item_id}) for item in parsed]
