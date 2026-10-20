"""Contract tests for the tag and explain services."""

import pytest

from utmelab_pipeline.adapters.providers.mock import MockProvider
from utmelab_pipeline.adapters.providers.tagging import (
    ExplainService,
    TagService,
    UnknownSubtopic,
    UnknownTopic,
)
from utmelab_pipeline.domain.models import CatalogSnapshot, CatalogSubtopic, CatalogTopic


def test_tag_service_applies_a_valid_subtopic(staging_item, catalog: CatalogSnapshot) -> None:
    service = TagService(MockProvider())
    result = __import__("asyncio").run(service.tag(staging_item, catalog))

    assert result.evidence.tag is not None
    assert result.evidence.tag.subtopic_id == "s1"
    assert result.state == "enriched"


def test_tag_service_refuses_an_unknown_topic(staging_item, catalog: CatalogSnapshot) -> None:
    class BadTagger(MockProvider):
        async def tag(self, request):
            from utmelab_pipeline.domain.models import TagProposal

            return TagProposal(
                topic_id="not-a-topic",
                subtopic_id="not-a-subtopic",
                evidence=request.item.content.stem.text,
                confidence=1.0,
                producer=self.producer,
            )

    service = TagService(BadTagger())
    with pytest.raises(UnknownTopic):
        __import__("asyncio").run(service.tag(staging_item, catalog))


def test_tag_service_refuses_a_subtopic_from_another_topic(
    staging_item, catalog: CatalogSnapshot
) -> None:
    class WrongParentTagger(MockProvider):
        async def tag(self, request):
            from utmelab_pipeline.domain.models import TagProposal

            return TagProposal(
                topic_id="t2",
                subtopic_id="s1",
                evidence=request.item.content.stem.text,
                confidence=1.0,
                producer=self.producer,
            )

    service = TagService(WrongParentTagger())
    with pytest.raises(UnknownSubtopic):
        __import__("asyncio").run(service.tag(staging_item, catalog))


def test_tag_service_refuses_evidence_that_is_not_in_the_question(
    staging_item, catalog: CatalogSnapshot
) -> None:
    class FabricatingTagger(MockProvider):
        async def tag(self, request):
            from utmelab_pipeline.domain.models import TagProposal

            return TagProposal(
                topic_id="t1",
                subtopic_id="s1",
                evidence="text that appears nowhere in the question",
                confidence=1.0,
                producer=self.producer,
            )

    service = TagService(FabricatingTagger())
    with pytest.raises(ValueError, match="evidence does not appear"):
        __import__("asyncio").run(service.tag(staging_item, catalog))


def test_explain_service_stores_the_explanation(staging_item, catalog: CatalogSnapshot) -> None:
    service = ExplainService(MockProvider())
    result = __import__("asyncio").run(service.explain(staging_item, catalog))

    assert result.evidence.explanation is not None
    assert result.state == "enriched"
