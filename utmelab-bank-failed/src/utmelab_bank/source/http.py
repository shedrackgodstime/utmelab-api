"""The polite session every source uses.

``fetch``, the user agent string and the spacing between requests were pasted
into each harvester. That is why one of them sent a request every 1.0 seconds
and another every 2.5, and why two of them sent a different user agent, which
makes the project harder to identify in somebody else's logs.

One session, one user agent, one delay, one retry policy.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncIterator
from typing import Any, Final

import httpx

from utmelab_bank.config import Config
from utmelab_bank.errors import SourceError

__all__ = ["RETRYABLE_STATUS", "PoliteSession"]

#: 429 is rate limited, so it is worth waiting out. 4xx generally is not.
RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({408, 425, 429, 500, 502, 503, 504})


class PoliteSession:
    """An httpx client that identifies itself, spaces requests, and retries.

    Spacing is enforced here rather than by callers sleeping, because two
    harvesters had different delays and the sleep lived in the caller, so there
    was no single place to see what rate we were hitting a third party at.
    """

    def __init__(self, config: Config, *, delay: float | None = None) -> None:
        self._config = config
        self._delay = config.http_delay_secs if delay is None else delay
        self._last_request = 0.0
        self._client = httpx.AsyncClient(
            timeout=config.http_timeout_secs,
            follow_redirects=True,
            headers={
                "User-Agent": config.http_user_agent,
                "Accept-Language": "en-NG,en;q=0.9",
            },
        )

    async def __aenter__(self) -> PoliteSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _wait_our_turn(self) -> None:
        """Sleep until the configured gap since the last request has passed."""
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self._delay:
            # A little jitter, so a retry storm does not become a synchronised
            # thundering herd against a site we are asking to be reasonable.
            await asyncio.sleep(self._delay - elapsed + random.uniform(0, 0.25))

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """One GET, spaced and retried."""
        return await self.request("GET", url, **kwargs)

    async def request(
        self,
        method: str,
        url: str,
        *,
        attempts: int = 3,
        **kwargs: Any,
    ) -> httpx.Response:
        """One request, spaced, with backoff on the statuses worth retrying.

        The status check is explicit. The old harvesters fed an html error page
        straight to the parser, which returned an empty list, and the script
        exited with a message blaming the page layout instead of the 404.
        """
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            await self._wait_our_turn()
            try:
                response = await self._client.request(method, url, **kwargs)
                self._last_request = time.monotonic()
            except httpx.HTTPError as exc:
                last = exc
                if attempt == attempts:
                    break
                await asyncio.sleep(min(2**attempt, 30))
                continue

            if response.status_code < 400:
                return response

            last = SourceError(
                f"the site answered {response.status_code}",
                url=url,
                status=response.status_code,
            )
            if response.status_code not in RETRYABLE_STATUS or attempt == attempts:
                break
            await asyncio.sleep(min(2**attempt, 30))

        raise last or SourceError("request failed", url=url)

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        """One GET, parsed as json, with the status checked first."""
        response = await self.get(url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(
                "the site answered with something that is not json",
                url=url,
                content_type=response.headers.get("content-type", "unknown"),
                preview=response.text[:200],
            ) from exc

    async def stream_lines(self, url: str, **kwargs: Any) -> AsyncIterator[str]:
        """Stream a response line by line, for a large text body."""
        async with self._client.stream("GET", url, **kwargs) as response:
            if response.status_code >= 400:
                raise SourceError(
                    f"the site answered {response.status_code}",
                    url=url,
                    status=response.status_code,
                )
            self._last_request = time.monotonic()
            async for line in response.aiter_lines():
                yield line
