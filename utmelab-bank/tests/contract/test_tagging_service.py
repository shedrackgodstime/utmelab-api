"""Contract tests for the tag and explain services."""

import asyncio

import pytest

from utmelab_pipeline.adapters.providers.mock import MockProvider
from utmelab_pipeline.adapters.providers.tagging import (
    ExplainService,
    TagService,
    UnknownSubtopic,
    UnknownTopic,
)
from utmelab_pipeline.domain.capabilities import TagRequest
from utmelab_pipeline.domain.models import (
    CatalogSnapshot,
    StagingItem,
    TagProposal,
)


def make_proposal(
    *,
    topic_id: str,
    subtopic_id: str,
    evidence: str,
) -> TagProposal:
    return TagProposal(
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        evidence=evidence,
        confidence=1.0,
        producer=MockProvider().producer,
    )


def test_tag_service_applies_a_valid_subtopic(
    staging_item: StagingItem, catalog: CatalogSnapshot
) -> None:
    service = TagService(MockProvider())
    result = asyncio.run(service.tag(staging_item, catalog))

    assert result.evidence.tag is not None
    assert result.evidence.tag.subtopic_id == "s1"
    assert result.state.value == "enriched"


def test_tag_service_refuses_an_unknown_topic(
    staging_item: StagingItem, catalog: CatalogSnapshot
) -> None:
    class BadTagger(MockProvider):
        async def tag(self, request: TagRequest) -> TagProposal:
            return make_proposal(
                topic_id="not-a-topic",
                subtopic_id="not-a-subtopic",
                evidence=request.item.content.stem.text,
            )

    service = TagService(BadTagger())
    with pytest.raises(UnknownTopic):
        asyncio.run(service.tag(staging_item, catalog))


def test_tag_service_refuses_a_subtopic_from_another_topic(
    staging_item: StagingItem, catalog: CatalogSnapshot
) -> None:
    class WrongParentTagger(MockProvider):
        async def tag(self, request: TagRequest) -> TagProposal:
            return make_proposal(
                topic_id="t2",
                subtopic_id="s1",
                evidence=request.item.content.stem.text,
            )

    service = TagService(WrongParentTagger())
    with pytest.raises(UnknownSubtopic):
        asyncio.run(service.tag(staging_item, catalog))


def test_tag_service_refuses_evidence_that_is_not_in_the_question(
    staging_item: StagingItem, catalog: CatalogSnapshot
) -> None:
    class FabricatingTagger(MockProvider):
        async def tag(self, request: TagRequest) -> TagProposal:
            return make_proposal(
                topic_id="t1",
                subtopic_id="s1",
                evidence="text that appears nowhere in the question",
            )

    service = TagService(FabricatingTagger())
    with pytest.raises(ValueError, match="evidence does not appear"):
        asyncio.run(service.tag(staging_item, catalog))


def test_explain_service_stores_the_explanation(
    staging_item: StagingItem, catalog: CatalogSnapshot
) -> None:
    service = ExplainService(MockProvider())
    result = asyncio.run(service.explain(staging_item, catalog))

    assert result.evidence.explanation is not None
    assert result.state.value == "enriched"
