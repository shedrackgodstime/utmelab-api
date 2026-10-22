"""The myschool.ng source.

The source only knows the exam, the subject and the year. It does not read the
catalog and it does not read the syllabus: the scrape asks the site for a
paper, and the catalogue step places the row later. That is what lets a scrape
run with a read-only production token and no catalog snapshot.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from utmelab_bank.domain.hashing import payload_hash
from utmelab_bank.domain.models import (
    CatalogSnapshot,
    Coverage,
    Scope,
    SourceCapabilities,
    SourceItem,
    SourceProfile,
    StagingItem,
)

from ..payload import adapt_payload, validate_payload
from .errors import SourceError
from .parser import (
    api_last_page,
    listing_url,
    parse_api_listing,
    parse_api_question,
    parse_json,
    slug_for,
)
from .subjects import known_exams, profile_subjects

__all__ = ["MyschoolSource"]

DEFAULT_RATE_LIMIT: Final[float] = 1.0
ATTEMPTS: Final[int] = 3
#: A page that trickles bytes can satisfy httpx's read timeout forever. Cap
#: the whole request so one stalled page cannot hold the scope open.
REQUEST_TIMEOUT: Final[float] = 45.0


class MyschoolSource:
    """The live classroom API for JAMB, WAEC and NECO."""

    needs_catalog = False

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        delay: float | None = None,
    ) -> None:
        self.profile = SourceProfile(
            name="myschool",
            version="2.0.0",
            exams=tuple(code.upper() for code in known_exams()),
            subjects=profile_subjects(),
            years=None,
            capabilities=SourceCapabilities(
                figures=True,
                rich_text=True,
                answer=True,
                sections=False,
                marks=True,
            ),
            rate_limit_per_second=DEFAULT_RATE_LIMIT,
        )
        self._client = client or httpx.AsyncClient(
            headers={
                "User-Agent": "utmelab-bank/2.0 (+https://utmelab.com)",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=15.0),
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._delay = delay if delay is not None else 1.0 / self.profile.rate_limit_per_second

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def probe(self, scope: Scope) -> Coverage:
        source_slug = slug_for(scope.exam, scope.subject)
        payload = await self._get_json(listing_url(scope.exam.lower(), source_slug, scope.year))
        rows = parse_api_listing(payload)
        return Coverage(
            source=self.profile.name,
            scope=scope,
            item_count=len(rows),
            has_more=api_last_page(payload) > 1,
        )

    async def fetch(self, scope: Scope) -> AsyncIterator[SourceItem]:
        source_slug = slug_for(scope.exam, scope.subject)
        exam = scope.exam.lower()
        year = scope.year
        page = 1

        while True:
            payload = await self._get_json(listing_url(exam, source_slug, year, page))
            rows = parse_api_listing(payload)
            if not rows:
                break

            for index, row in enumerate(rows, start=1):
                try:
                    parsed = parse_api_question(
                        row,
                        exam=exam,
                        subject=scope.subject,
                        year=year,
                        source_slug=source_slug,
                    )
                except SourceError as exc:
                    yield self._error_item(
                        scope, source_slug, exam, year, page, index, row, str(exc)
                    )
                    continue

                if parsed.exam != exam or parsed.year != year:
                    yield self._error_item(
                        scope,
                        source_slug,
                        exam,
                        year,
                        page,
                        index,
                        row,
                        f"the row is from {parsed.exam} {parsed.year}, not {exam} {year}",
                    )
                    continue

                # The parser turns every data: URL into a blob marker and
                # keeps its bytes here. The media list only carries resolved
                # urls or blob: markers, so there is nothing left to decode.
                media_blobs: dict[str, bytes] = dict(parsed.payload.get("media_blobs", {}))

                # Remove media_blobs from payload before hashing (bytes not JSON-serializable)
                payload_for_hash = {k: v for k, v in parsed.payload.items() if k != "media_blobs"}

                yield SourceItem(
                    source=self.profile.name,
                    source_url=parsed.source_url,
                    source_item_id=parsed.source_item_id,
                    fetched_at=datetime.now(UTC),
                    payload=payload_for_hash,
                    payload_hash=payload_hash(payload_for_hash),
                    scope=scope,
                    source_version=self.profile.version,
                    media_blobs=media_blobs,
                )

            last_page = api_last_page(payload)
            if page >= last_page:
                break
            await asyncio.sleep(self._delay)
            page += 1

    def adapt(self, item: SourceItem, catalog: CatalogSnapshot | None) -> StagingItem:
        return adapt_payload(item, catalog)

    def validate(self, item: SourceItem) -> list[str]:
        return validate_payload(item.payload)

    def _error_item(
        self,
        scope: Scope,
        source_slug: str,
        exam: str,
        year: int,
        page: int,
        index: int,
        row: dict[str, Any],
        message: str,
    ) -> SourceItem:
        item_id = str(row.get("id") or f"page-{page}-row-{index}")
        payload: dict[str, Any] = {"error": message}
        return SourceItem(
            source=self.profile.name,
            source_url=f"{listing_url(exam, source_slug, year, page)}#{item_id}",
            source_item_id=item_id,
            fetched_at=datetime.now(UTC),
            payload=payload,
            payload_hash=payload_hash(payload),
            scope=scope,
            source_version=self.profile.version,
        )

    async def _get_json(self, url: str) -> dict[str, Any]:
        """Fetch one API page, retrying a transient failure three times.

        A 4xx is a refusal and is not retried. A DNS failure, a timeout or a
        5xx gets three attempts with a short backoff; a scrape of a whole
        paper is twenty requests, and one lost connection should not cost the
        run.
        """
        last_error = ""
        for attempt in range(ATTEMPTS):
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    response = await self._client.get(url)
                    if response.status_code >= 500:
                        last_error = f"http {response.status_code}"
                    else:
                        response.raise_for_status()
                        return parse_json(response.text)
            except TimeoutError:
                last_error = f"no complete response in {REQUEST_TIMEOUT:.0f}s"
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise SourceError(
                        f"the api answered {exc.response.status_code}",
                        url=url,
                    ) from exc
                last_error = f"http {exc.response.status_code}"
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < ATTEMPTS - 1:
                await asyncio.sleep(2.0 * (attempt + 1))
        raise SourceError(
            f"the api did not answer after {ATTEMPTS} attempts: {last_error}",
            url=url,
        )
