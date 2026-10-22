"""The provider seam: the one interface a model backend must satisfy.

One method, ``async complete(prompt) -> str``. The task layer never imports a
concrete backend, so the model is swappable by adding a module and a line in
:func:`build_provider`. Ported from ``tools/utmetag/providers/``, adapted so
the model id, timeout and retry budget come from the run's config.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
from typing import Final, Protocol, runtime_checkable

from utmelab_bank.config import Config
from utmelab_bank.errors import AiError

__all__ = ["MockProvider", "OpenCodeProvider", "Provider", "build_provider"]

log = logging.getLogger(__name__)

DEFAULT_MODEL: Final[str] = "opencode/space-bunny-free"


@runtime_checkable
class Provider(Protocol):
    """A model backend. One method: ``complete(prompt) -> str``."""

    name: str

    async def complete(self, prompt: str, *, image: str | None = None) -> str:
        """Return the model's raw text reply for one prompt.

        ``image`` is an absolute path to a figure to attach. Only the vision
        tasks pass it; a text task leaves it ``None``.
        """
        ...

    async def aclose(self) -> None:
        """Release any resources (subprocesses, clients)."""
        ...


class OpenCodeProvider:
    """Runs prompts through the ``opencode run`` CLI, free Zen models.

    The prompt is fed via **stdin**: passing it as an argv positional breaks on
    stems containing tokens like ``-3x``. ``--format json`` emits
    newline-delimited JSON events; assistant text lives in ``type=="text"``.
    """

    def __init__(
        self, config: Config, *, binary: str = "opencode", model: str | None = None
    ) -> None:
        self.model = model or config.ai_model
        self.binary = binary
        self.timeout = float(config.ai_timeout_secs)
        self.max_attempts = config.ai_max_attempts
        self.retry_delay = 3.0
        self.name = f"opencode:{self.model}"

    def _argv(self, image: str | None = None) -> list[str]:
        """The command line. The prompt itself goes on stdin, never argv."""
        cmd = [self.binary, "run", "--model", self.model, "--format", "json"]
        if image:
            cmd += ["--file", image]
        return cmd

    async def complete(self, prompt: str, *, image: str | None = None) -> str:
        cmd = self._argv(image)
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
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
                except TimeoutError:
                    proc.kill()
                    raise AiError(f"opencode timed out after {self.timeout}s") from None
                if proc.returncode != 0:
                    raise AiError(
                        f"opencode exited {proc.returncode}",
                        stderr=stderr.decode(errors="replace")[:500],
                    )
                text = self.extract_text(stdout.decode())
                if not text:
                    raise AiError("opencode produced no text output")
                return text
            except AiError as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    wait = self.retry_delay * (2 ** (attempt - 1))
                    log.warning(
                        "opencode attempt %d failed: %s; retrying in %.1fs", attempt, exc, wait
                    )
                    await asyncio.sleep(wait)
                else:
                    raise
            except Exception as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    wait = self.retry_delay * (2 ** (attempt - 1))
                    log.warning(
                        "opencode attempt %d failed: %s; retrying in %.1fs", attempt, exc, wait
                    )
                    await asyncio.sleep(wait)
                else:
                    raise AiError(f"failed after {self.max_attempts} attempts: {exc}") from exc

        raise last_error or AiError("opencode failed with no error")

    @staticmethod
    def extract_text(raw: str) -> str:
        """Concatenate assistant text parts from NDJSON events, or fall back to raw."""
        parts: list[str] = []
        saw_event = False
        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "text":
                saw_event = True
                text = event.get("part", {}).get("text")
                if text:
                    parts.append(text)
        if saw_event:
            return "".join(parts)
        lines = [ln for ln in raw.splitlines() if ln and not ln.lstrip().startswith(">")]
        return "\n".join(lines).strip()

    async def aclose(self) -> None:
        return None


class MockProvider:
    """Deterministic mock, no network I/O. For tests and offline runs."""

    def __init__(self, seed_salt: str = "") -> None:
        self.seed_salt = seed_salt
        self.name = "mock"

    async def complete(self, prompt: str, *, image: str | None = None) -> str:
        # The mock cannot see, so it accepts the protocol's image and ignores it.
        _ = image
        seed = int(hashlib.md5((self.seed_salt + prompt).encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        subtopic_slug = None
        match = re.search(
            r"AVAILABLE SUBTOPICS[^\n]*\n(.*?)(?:\n[ \t]*\nAVAILABLE TOPICS|\Z)",
            prompt,
            re.DOTALL,
        )
        if match:
            slugs = re.findall(r"^  - (\S+):", match.group(1), re.MULTILINE)
            if slugs:
                subtopic_slug = rng.choice(slugs)

        underline = None
        stem_match = re.search(r"Question: (.*?)\n\nOPTIONS:", prompt, re.DOTALL)
        stem = stem_match.group(1) if stem_match else ""
        if "underlin" in stem.lower():
            uw = re.search(r"underlined (?:word|portion)[:\s]+([^\.\n]+)", stem, re.IGNORECASE)
            if uw:
                word = uw.group(1).strip().strip('":')
            else:
                words = [w for w in stem.split() if len(w) > 3 and w.isalpha()]
                word = rng.choice(words) if words else None
            if word:
                start = stem.find(word)
                if start >= 0:
                    underline = {"word": word, "start": start, "len": len(word)}

        return json.dumps(
            {
                "subtopic_slug": subtopic_slug,
                "underline": underline,
                "answer_correct": rng.random() > 0.1,
                "explanation_quality": rng.choice(["GOOD", "PARTIAL", "GOOD", "GOOD"]),
                "confidence": round(0.7 + rng.random() * 0.3, 2),
                "reasoning": (
                    "Mock response for testing pipeline. Subtopic assigned from "
                    "available list. Answer verified against provided solution. "
                    "Explanation quality assessed."
                ),
            }
        )

    async def aclose(self) -> None:
        return None


def build_provider(
    config: Config, engine: str = "opencode", *, model: str | None = None
) -> Provider:
    """Construct a Provider for the named engine, driven by the run's config.

    ``model`` overrides the configured model when a task needs a different
    capability (``ai-describe`` takes the image model when one is set).
    """
    if engine == "mock":
        return MockProvider()
    if engine == "opencode":
        return OpenCodeProvider(config, model=model)
    raise AiError(f"unknown engine {engine!r}", engine=engine, known=["opencode", "mock"])
