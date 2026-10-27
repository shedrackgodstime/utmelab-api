import asyncio

from tests.fakes.mock_provider import MockProvider
from utmelab_bank.domain.capabilities import (
    DescribeImageRequest,
    ExplainRequest,
    TagRequest,
    VerifyAnswerRequest,
)
from utmelab_bank.domain.enums import Verdict
from utmelab_bank.domain.models import CatalogSnapshot, MediaAsset, StagingItem
from utmelab_bank.domain.ports import (
    AnswerVerifier,
    Explainer,
    ImageDescriber,
    Tagger,
)


def test_mock_matches_every_capability_port() -> None:
    provider = MockProvider()
    assert isinstance(provider, ImageDescriber)
    assert isinstance(provider, Explainer)
    assert isinstance(provider, Tagger)
    assert isinstance(provider, AnswerVerifier)


def test_mock_describe(media: MediaAsset) -> None:
    provider = MockProvider()
    result = asyncio.run(provider.describe(DescribeImageRequest(asset=media, context="cell")))
    assert result.asset_id == media.asset_id
    assert result.producer.provider == "mock"


def test_mock_explain(staging_item: StagingItem) -> None:
    provider = MockProvider()
    result = asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))
    assert "test" in result.body.text or "Mock" in result.body.text


def test_mock_tag_uses_a_real_subtopic(staging_item: StagingItem, catalog: CatalogSnapshot) -> None:
    provider = MockProvider()
    result = asyncio.run(provider.tag(TagRequest(item=staging_item, catalog=catalog)))
    assert result.topic_id == "t1"
    assert result.subtopic_id == "s1"
    assert result.evidence == "test evidence" or result.evidence is not None


def test_mock_verify(staging_item: StagingItem) -> None:
    provider = MockProvider()
    result = asyncio.run(provider.verify(VerifyAnswerRequest(item=staging_item, catalog=None)))
    assert result.verdict == "pass"


def test_mock_can_abstain(staging_item: StagingItem) -> None:
    provider = MockProvider(verdict=Verdict.ABSTAIN)
    result = asyncio.run(provider.verify(VerifyAnswerRequest(item=staging_item, catalog=None)))
    assert result.verdict == "abstain"
