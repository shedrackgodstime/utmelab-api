import asyncio
from types import SimpleNamespace

from utmelab_bank.adapters.providers.openai_compatible import OpenAICompatibleProvider
from utmelab_bank.domain.capabilities import ExplainRequest, TagRequest, VerifyAnswerRequest
from utmelab_bank.domain.enums import Verdict
from utmelab_bank.domain.models import CatalogSnapshot, StagingItem


class FakeCompletions:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        import json

        return SimpleNamespace(
            choices=(SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.payload))),)
        )


class FakeClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(payload))


def provider(payload: dict[str, object]) -> tuple[OpenAICompatibleProvider, FakeCompletions]:
    client = FakeClient(payload)
    built = OpenAICompatibleProvider(
        api_key="key",
        base_url="https://example.test/v1",
        model="test/model",
        client=client,
    )
    return built, client.chat.completions


def test_openai_compatible_provider_parses_explanation(staging_item: StagingItem) -> None:
    built, calls = provider({"key_point": "k", "body": "b", "confidence": 0.9})

    result = asyncio.run(built.explain(ExplainRequest(item=staging_item)))

    assert result.body.text == "b"
    assert calls.calls[0]["model"] == "test/model"
    assert calls.calls[0]["response_format"] == {"type": "json_object"}
    assert calls.calls[0]["max_tokens"] == 2048


def test_openai_compatible_provider_parses_tag_and_verdict(
    staging_item: StagingItem, catalog: CatalogSnapshot
) -> None:
    tagger, _ = provider(
        {"topic_id": "t1", "subtopic_id": "s1", "evidence": "What is 2 + 2?", "confidence": 0.9}
    )
    tag = asyncio.run(tagger.tag(TagRequest(item=staging_item, catalog=catalog)))
    assert tag.subtopic_id == "s1"

    verifier, _ = provider({"verdict": "pass", "reasoning": "r", "confidence": 0.9})
    verdict = asyncio.run(verifier.verify(VerifyAnswerRequest(item=staging_item, catalog=catalog)))
    assert verdict.verdict is Verdict.PASS
