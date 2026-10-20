"""OpenCode CLI provider.

Runs prompts through the ``opencode run`` CLI, which uses OpenCode Zen free
models from *within* the client. That is what makes this free: no API key, no
per-IP limit, no external chat endpoint (the external Zen chat endpoint is
rejected with ``FreeTierError`` for direct HTTP callers).

The prompt is fed via **stdin**. Passing it as an argv positional breaks on
stems containing tokens like ``-3x`` (yargs misreads them as flags).
``--format json`` emits newline-delimited JSON events; assistant text lives in
events with ``type == "text"``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from .base import Provider


class OpenCodeProvider(Provider):
    def __init__(
        self,
        model: str = "opencode/space-bunny-free",
        binary: str = "opencode",
        timeout: float = 180.0,
        max_retries: int = 2,
        retry_delay: float = 3.0,
    ):
        self.model = model
        self.binary = binary
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.name = f"opencode:{model}"

    async def complete(self, prompt: str) -> str:
        cmd = [self.binary, "run", "--model", self.model, "--format", "json"]
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(input=prompt.encode()), timeout=self.timeout
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    raise RuntimeError(f"opencode timed out after {self.timeout}s")
                if proc.returncode != 0:
                    raise RuntimeError(f"opencode exited {proc.returncode}: {stderr.decode()[:500]}")
                text = self.extract_text(stdout.decode())
                if not text:
                    raise ValueError("opencode produced no text output")
                return text
            except Exception as e:  # noqa: BLE001 - retried below
                last_error = e
                if attempt < self.max_retries - 1:
                    wait = self.retry_delay * (2 ** attempt)
                    print(f"  opencode attempt {attempt + 1} failed: {e}. Retrying in {wait:.1f}s...")
                    await asyncio.sleep(wait)
                else:
                    raise Exception(f"Failed after {self.max_retries} attempts: {last_error}")

    @staticmethod
    def extract_text(raw: str) -> str:
        """Concatenate assistant text parts from NDJSON events, or fall back to raw."""
        parts: list[str] = []
        saw_event = False
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "text":
                saw_event = True
                t = event.get("part", {}).get("text")
                if t:
                    parts.append(t)
        if saw_event:
            return "".join(parts)
        # Fallback: strip the "> model" banner line and return the rest.
        lines = [ln for ln in raw.splitlines() if ln and not ln.lstrip().startswith(">")]
        return "\n".join(lines).strip()

    async def aclose(self) -> None:
        pass
