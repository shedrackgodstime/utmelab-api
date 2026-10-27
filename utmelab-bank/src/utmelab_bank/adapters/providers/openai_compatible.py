"""Provider for OpenAI-compatible chat completion APIs."""

from __future__ import annotations

import base64
import inspect
import json
from typing import Any, TypeVar, cast

from pydantic import BaseModel

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
from utmelab_bank.domain.ports import AnswerVerifier, Explainer, ImageDescriber, Tagger

from .catalog_prompt import catalog_for_prompt

M = TypeVar("M", bound=BaseModel)


class OpenAICompatibleError(RuntimeError):
    """A classified failure from an OpenAI-compatible provider."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "provider",
        status: int | None = None,
        provider: str = "openai",
    ) -> None:
        self.provider = provider
        self.category = category
        self.status = status
        label = f"provider={self.provider} category={category}"
        if status is not None:
            label += f" status={status}"
        super().__init__(f"{label}: {message}")


class OpenAICompatibleProvider(ImageDescriber, Explainer, Tagger, AnswerVerifier):
    """Use any OpenAI-compatible endpoint through the official SDK.

    NVIDIA is the first deployment target, but the adapter does not encode
    NVIDIA-specific behavior. Change the key, base URL, and model to use
    another compatible service.
    """

    capabilities = frozenset(Capability)

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        provider_name: str = "openai",
        account_id: str | None = None,
        client: Any | None = None,
        timeout: float = 120.0,
        max_tokens: int = 2048,
        max_retries: int = 0,
    ) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        if not base_url:
            raise ValueError("an OpenAI-compatible base URL is required")
        if not model:
            raise ValueError("an OpenAI-compatible model is required")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
            )
        self._client = client
        self.producer = Producer(provider=provider_name, model=model)
        self._provider_name = provider_name
        self.account_id = account_id
        self._max_tokens = max_tokens

    async def describe(self, request: DescribeImageRequest) -> ImageDescription:
        if request.data is None:
            raise OpenAICompatibleError("describe_image needs image bytes", category="input")
        mime = request.asset.mime
        image = base64.b64encode(request.data).decode("ascii")
        prompt = (
            "Describe only visible facts in this exam figure. Include labels, values, units, "
            "axes, arrows, and relationships when readable. Do not infer the answer. "
            'Return exactly {"description": "string", "facts": ["string"], '
            '"confidence": 0.0}. Every facts entry must be a plain string, never an object. '
            "Do not add other fields."
        )
        data = await self._complete(
            [
                {"role": "system", "content": "Return exactly one JSON object."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"{prompt}\nContext: {request.context or ''}"},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image}"}},
                    ],
                },
            ]
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
        data = await self._complete(
            self._text_messages(
                "Explain the canonical answer and every distractor. Show calculations, preserve "
                "units, and use figure evidence only when supported. Return a JSON object with "
                'exactly these keys: "key_point" (one sentence stating the key idea), "body" '
                "(the full explanation, including why each distractor is wrong), "
                '"trap" (the most likely mistake, or "none"), and "confidence" (a number '
                "from 0.0 to 1.0). Do not add any other keys.",
                self._content_payload(request.item),
            )
        )
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
        payload["catalog"] = catalog_for_prompt(request.catalog, request.item.content.stem.text)
        data = await self._complete(
            self._text_messages(
                "Choose one catalog topic and subtopic. Return a JSON object with exactly "
                'these keys: "topic_id" (an id from catalog.topics), "subtopic_id" (an id '
                "from catalog.subtopics whose topic_id matches the chosen topic), "
                '"evidence" (an exact quote from the question, passage, or accepted OCR '
                'text), and "confidence" (a number from 0.0 to 1.0). Use the ids, not the '
                "names. Do not add any other keys.",
                payload,
            )
        )
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
        data = await self._complete(
            self._text_messages(
                "Verify the canonical answer. Return a JSON object with exactly these keys: "
                '"verdict" ("pass", "fail", or "abstain"), "reasoning" (plain text), and '
                '"confidence" (a number from 0.0 to 1.0). Do not add any other keys.',
                self._content_payload(request.item),
            )
        )
        return self._validate(
            AnswerVerdict,
            {
                "verdict": data.get("verdict", "abstain"),
                "reasoning": data.get("reasoning"),
                "confidence": data.get("confidence"),
                "producer": self.producer,
            },
        )

    async def _complete(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            response_or_awaitable = cast(Any, self._client.chat.completions.create)(
                model=self.producer.model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=self._max_tokens,
                temperature=0,
            )
            response = (
                await response_or_awaitable
                if inspect.isawaitable(response_or_awaitable)
                else response_or_awaitable
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            error_type = type(exc).__name__
            if status == 401:
                category = "authentication"
            elif status == 429:
                category = "rate_limit"
            elif status == 404:
                category = "not_found"
            elif error_type in {"APITimeoutError", "ConnectTimeout", "ReadTimeout"}:
                category = "timeout"
            else:
                category = "transport"
            raise OpenAICompatibleError(
                str(exc), category=category, status=status, provider=self._provider_name
            ) from exc
        try:
            content = response.choices[0].message.content
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise TypeError("response JSON must be an object")
            return cast(dict[str, Any], payload)
        except (AttributeError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise OpenAICompatibleError(
                "response was not a JSON object", category="output", provider=self._provider_name
            ) from exc

    def _text_messages(self, instruction: str, payload: object) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": "Return exactly one JSON object and nothing else."},
            {
                "role": "user",
                "content": f"{instruction}\nInput:\n{json.dumps(payload, ensure_ascii=False)}",
            },
        ]

    def _content_payload(self, item: StagingItem) -> dict[str, Any]:
        return {
            "content": item.content.model_dump(mode="json"),
            "media_checks": [c.model_dump(mode="json") for c in item.evidence.media_checks],
            "ocr": [record.model_dump(mode="json") for record in item.evidence.ocr],
            "image_descriptions": [
                d.model_dump(mode="json") for d in item.evidence.image_descriptions
            ],
        }

    def _validate(self, model_type: type[M], data: dict[str, Any]) -> M:
        if model_type is Explanation:
            for field in ("key_point", "body", "trap"):
                if isinstance(data.get(field), str):
                    data[field] = RichText(text=data[field])
        try:
            return model_type.model_validate(data)
        except Exception as exc:
            raise OpenAICompatibleError(
                "provider output failed schema validation",
                category="output",
                provider=self._provider_name,
            ) from exc
