"""OpenAI-compatible HTTP provider.

Free, no-key option: Pollinations (``https://text.pollinations.ai/openai``),
which speaks the chat-completions API. Its anonymous tier allows roughly one
request per 30s per IP, so ``min_interval`` throttles request starts and the
runner forces concurrency to 1 when the interval is non-zero.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from .base import Provider

try:  # only needed for this engine
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


class HTTPProvider(Provider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        temperature: float = 0.1,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        min_interval: float = 0.0,
    ):
        if httpx is None:
            raise RuntimeError("the 'http' engine requires the httpx package (pip install httpx)")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.min_interval = max(0.0, min_interval)
        self.name = f"http:{model}"
        self._rate_lock = asyncio.Lock()
        self._last_call = 0.0
        self.client = httpx.AsyncClient(timeout=120.0)

    async def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._rate_lock:
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def complete(self, prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an expert JAMB/WAEC examiner. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": 800,
        }
        if "pollinations" in self.base_url or any(k in self.model.lower() for k in ("gpt", "o1", "deepseek")):
            payload["response_format"] = {"type": "json_object"}

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            await self._throttle()
            try:
                response = await self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if content is None:
                    raise ValueError("API returned null message content")
                return content
            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code
                try:
                    body = e.response.json()
                except Exception:  # noqa: BLE001
                    body = e.response.text
                print(f"  API Error: {status} - {body}")
                if attempt < self.max_retries - 1:
                    base = self.min_interval if status in (402, 429) and self.min_interval else self.retry_delay
                    wait = max(base, self.retry_delay) * (2 ** attempt)
                    print(f"  Attempt {attempt + 1} failed. Retrying in {wait:.1f}s...")
                    await asyncio.sleep(wait)
                else:
                    raise Exception(f"Failed after {self.max_retries} attempts: {last_error}")
            except Exception as e:  # noqa: BLE001
                last_error = e
                if attempt < self.max_retries - 1:
                    wait = self.retry_delay * (2 ** attempt)
                    print(f"  Attempt {attempt + 1} failed: {e}. Retrying in {wait:.1f}s...")
                    await asyncio.sleep(wait)
                else:
                    raise Exception(f"Failed after {self.max_retries} attempts: {last_error}")
        raise Exception(f"Failed after {self.max_retries} attempts: {last_error}")

    async def aclose(self) -> None:
        await self.client.aclose()
