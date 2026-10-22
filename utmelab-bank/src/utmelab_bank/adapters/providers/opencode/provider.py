"""An OpenCode provider. The CLI transport stays inside this adapter."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ValidationError

from utmelab_bank.adapters.providers.catalog_prompt import catalog_for_prompt
from utmelab_bank.domain.capabilities import (
    DescribeImageRequest,
    ExplainRequest,
    TagRequest,
    VerifyAnswerRequest,
)
from utmelab_bank.domain.enums import Capability
from utmelab_bank.domain.models import (
    AnswerVerdict,
    Explanation,
    ImageDescription,
    Producer,
    RichText,
    StagingItem,
    TagProposal,
)

M = TypeVar("M", bound=BaseModel)


class OpenCodeError(RuntimeError):
    """Raised when the OpenCode CLI fails, times out, or returns junk."""


#: The failures that are the server's, not the prompt's.
#:
#: The free models answer through a shared queue. A call can fail with an
#: ``UnknownError`` or a usage limit and then succeed a moment later, and the
#: message is the only thing that distinguishes that from a bad request. A
#: second call costs seconds; a lost row costs a whole answer.
TRANSIENT_MARKERS = (
    "unexpected server error",
    "usage limit",
    "rate limit",
    "too many requests",
    "overloaded",
    "temporarily unavailable",
    "try again",
    "timed out",
    "server error",
    " 429",
    " 500",
    " 502",
    " 503",
    " 504",
)


def _is_transient(message: str) -> bool:
    lower = message.lower()
    return any(marker in lower for marker in TRANSIENT_MARKERS)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    async def run(self, argv: list[str], *, timeout: float) -> CommandResult: ...


class SubprocessRunner:
    def __init__(self, *, command: str = "opencode") -> None:
        self._command = command

    async def run(self, argv: list[str], *, timeout: float) -> CommandResult:
        process = await asyncio.create_subprocess_exec(
            self._command,
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        code = process.returncode if process.returncode is not None else -1
        return CommandResult(
            returncode=code,
            stdout=stdout.decode("utf-8", "replace"),
            stderr=stderr.decode("utf-8", "replace"),
        )


class OpenCodeProvider:
    """Calls `opencode run --format json` and validates the returned proposal."""

    def __init__(
        self,
        *,
        model: str,
        runner: CommandRunner | None = None,
        timeout: float = 90.0,
        command: str = "opencode",
        capabilities: frozenset[Capability] = frozenset(Capability),
        retries: int = 3,
        retry_delay: float = 5.0,
    ) -> None:
        self.producer = Producer(provider="opencode", model=model)
        self.capabilities = capabilities
        self._runner = runner or SubprocessRunner(command=command)
        self._timeout = timeout
        self._retries = max(1, retries)
        self._retry_delay = retry_delay

    async def describe(self, request: DescribeImageRequest) -> ImageDescription:
        prompt = self._prompt(
            "Describe the attached image for an exam question. Return JSON with keys "
            "description (string), facts (array of strings), confidence (number from 0 to 1).",
            {"context": request.context, "mime": request.asset.mime},
        )
        # The asset url is where the row serves the figure, not where the
        # bytes are on this machine. When the caller hands us the bytes, the
        # provider writes its own scratch file; the local-path branch remains
        # for a store that really does address a file.
        if request.data is not None:
            path = _write_scratch(request.data, request.asset.mime)
            try:
                data = self._extract_json(await self._complete(prompt, files=(path,)))
            finally:
                path.unlink(missing_ok=True)
        else:
            data = self._extract_json(
                await self._complete(prompt, files=(_local_asset_path(request.asset.storage_url),))
            )
        return self._validate(
            ImageDescription,
            {
                "asset_id": request.asset.asset_id,
                "description": data.get("description"),
                "facts": data.get("facts", []),
                "confidence": data.get("confidence"),
                "producer": self.producer,
            },
        )

    async def explain(self, request: ExplainRequest) -> Explanation:
        prompt = self._prompt(
            "Explain why the stated answer is correct and why the other options are wrong. "
            "Return JSON with keys key_point (string), body (string), "
            "trap (string or null), confidence (number from 0 to 1).",
            self._content_payload(request.item),
        )
        data = self._extract_json(await self._complete(prompt))
        return self._validate(
            Explanation,
            {
                "key_point": data.get("key_point"),
                "body": data.get("body"),
                "trap": data.get("trap"),
                "confidence": data.get("confidence"),
                "producer": self.producer,
            },
        )

    async def tag(self, request: TagRequest) -> TagProposal:
        payload = self._content_payload(request.item)
        payload["catalog"] = catalog_for_prompt(
            request.catalog,
            request.item.content.stem.text,
        )
        prompt = self._prompt(
            "Choose one topic id and one subtopic id from the catalog. The evidence must be an "
            "exact quote from the stem or passage. Return JSON with keys topic_id (string), "
            "subtopic_id (string), evidence (string), confidence (number from 0 to 1).",
            payload,
        )
        data = self._extract_json(await self._complete(prompt))
        return self._validate(
            TagProposal,
            {
                "topic_id": data.get("topic_id"),
                "subtopic_id": data.get("subtopic_id"),
                "evidence": data.get("evidence"),
                "confidence": data.get("confidence"),
                "producer": self.producer,
            },
        )

    async def verify(self, request: VerifyAnswerRequest) -> AnswerVerdict:
        prompt = self._prompt(
            "Decide whether the stated answer is correct. Return JSON with keys "
            'verdict ("pass", "fail", or "abstain"), reasoning (string), '
            "confidence (number from 0 to 1).",
            self._content_payload(request.item),
        )
        data = self._extract_json(await self._complete(prompt))
        return self._validate(
            AnswerVerdict,
            {
                "verdict": data.get("verdict", "abstain"),
                "reasoning": data.get("reasoning"),
                "confidence": data.get("confidence"),
                "producer": self.producer,
            },
        )

    async def _complete(self, prompt: str, files: tuple[Path, ...] = ()) -> str:
        argv = ["run", "--format", "json", "-m", self.producer.model]
        for path in files:
            argv.extend(["-f", str(path)])
        argv.append(prompt)
        last: OpenCodeError | None = None
        for attempt in range(self._retries):
            final = attempt == self._retries - 1
            try:
                result = await self._runner.run(argv, timeout=self._timeout)
            except TimeoutError as exc:
                error = OpenCodeError(f"opencode timed out after {self._timeout} seconds")
                if final:
                    raise error from exc
                last = error
            else:
                if result.returncode != 0:
                    detail = result.stderr.strip() or result.stdout.strip()
                    error = OpenCodeError(
                        f"opencode failed with exit code {result.returncode}: {detail}"
                    )
                    if final or not _is_transient(detail):
                        raise error
                    last = error
                else:
                    try:
                        return self._collect_text(result.stdout)
                    except OpenCodeError as exc:
                        if final or not _is_transient(str(exc)):
                            raise
                        last = exc
            await asyncio.sleep(self._retry_delay * (attempt + 1))
        raise last or OpenCodeError("opencode did not answer")

    def _content_payload(self, item: StagingItem) -> dict[str, Any]:
        return {
            "content": item.content.model_dump(mode="json"),
            "image_descriptions": [
                description.model_dump(mode="json")
                for description in item.evidence.image_descriptions
            ],
            "gate": (
                item.evidence.gate.model_dump(mode="json")
                if item.evidence.gate is not None
                else None
            ),
        }

    def _prompt(self, instruction: str, payload: object) -> str:
        return (
            "You are a careful exam content assistant. "
            "Return exactly one JSON object and nothing else. Do not use markdown fences.\n"
            f"{instruction}\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )

    def _validate(self, model_type: type[M], data: dict[str, Any]) -> M:
        # Convert string fields to RichText for models that expect RichText objects
        if model_type.__name__ == "Explanation":
            data = dict(data)
            for field in ("key_point", "body", "trap"):
                if field in data and isinstance(data[field], str):
                    data[field] = RichText(text=data[field])
        try:
            return model_type.model_validate(data)
        except ValidationError as exc:
            raise OpenCodeError(f"model output did not match {model_type.__name__}") from exc

    @staticmethod
    def _collect_text(stdout: str) -> str:
        texts: list[str] = []
        errors: list[str] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OpenCodeError("opencode returned a non-JSON line") from exc
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "error":
                errors.append(_error_message(event))
                continue
            if kind != "text":
                continue
            part = event.get("part")
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
        if errors:
            raise OpenCodeError("; ".join(errors))
        if not texts:
            raise OpenCodeError("opencode returned no text events")
        return "\n".join(texts)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise OpenCodeError("model output did not contain a JSON object")
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OpenCodeError("model output was not valid JSON") from exc
        if not isinstance(data, dict):
            raise OpenCodeError("model output must be a JSON object")
        return cast(dict[str, Any], data)


def _error_message(event: dict[str, Any]) -> str:
    """Read the message out of an opencode error event."""
    error = event.get("error")
    if isinstance(error, dict):
        data = error.get("data")
        if isinstance(data, dict):
            message = data.get("message")
            if isinstance(message, str):
                return message
        name = error.get("name")
        if isinstance(name, str):
            return name
    return "opencode reported an error"


def _write_scratch(data: bytes, mime: str) -> Path:
    """Write the bytes to a scratch file the CLI can attach, named by mime."""
    suffix = mimetypes.guess_extension(mime) or ".img"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(data)
        name = handle.name
    return Path(name)


def _local_asset_path(storage_url: str) -> Path:
    parsed = urlparse(storage_url)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
    elif parsed.scheme == "":
        path = Path(storage_url)
    else:
        raise OpenCodeError("describe_image needs a local asset path")
    if not path.is_file():
        raise OpenCodeError(f"asset file does not exist: {path}")
    return path
