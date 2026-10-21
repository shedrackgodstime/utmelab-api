"""Tag and explain capabilities. The core validates, the model proposes."""

from __future__ import annotations

from typing import Optional

from utmelab_bank.domain.capabilities import ExplainRequest, TagRequest
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.ports import Explainer, Tagger
from utmelab_bank.domain.models import (
    CatalogSnapshot,
    Explanation,
    StagingItem,
    TagProposal,
)


class UnknownSubtopic(ValueError):
    """Raised when a provider names a subtopic that is not in the snapshot."""


class UnknownTopic(ValueError):
    """Raised when a provider names a topic that is not in the snapshot."""


class TagService:
    """Tag a staging item and refuse a choice the catalog does not contain."""

    def __init__(self, tagger: Tagger) -> None:
        self._tagger = tagger

    async def tag(self, item: StagingItem, catalog: CatalogSnapshot) -> StagingItem:
        request = TagRequest(item=item, catalog=catalog)
        proposal = await self._tagger.tag(request)
        self._validate(proposal, catalog, item)
        return self._apply(item, proposal)

    def _validate(
        self,
        proposal: TagProposal,
        catalog: CatalogSnapshot,
        item: StagingItem,
    ) -> None:
        topic = next((t for t in catalog.topics if t.id == proposal.topic_id), None)
        if topic is None:
            raise UnknownTopic(
                f"provider named topic {proposal.topic_id!r} which is not in the catalog"
            )
        subtopic = next((s for s in catalog.subtopics if s.id == proposal.subtopic_id), None)
        if subtopic is None:
            raise UnknownSubtopic(
                f"provider named subtopic {proposal.subtopic_id!r} which is not in the catalog"
            )
        if subtopic.topic_id != proposal.topic_id:
            raise UnknownSubtopic(
                f"subtopic {subtopic.id!r} does not belong to topic {proposal.topic_id!r}"
            )
        if not _evidence_present(item_text=proposal.evidence, item=item):
            raise ValueError("tag evidence does not appear in the question or passage")

    def _apply(self, item: StagingItem, proposal: TagProposal) -> StagingItem:
        evidence = item.evidence.model_copy(update={"tag": proposal})
        updated = item.model_copy(
            update={
                "evidence": evidence,
                "catalog": item.catalog.model_copy(
                    update={
                        "topic_id": proposal.topic_id,
                        "subtopic_id": proposal.subtopic_id,
                    }
                )
                if item.catalog is not None
                else None,
            }
        )
        return updated.transition_to(State.ENRICHED)


class ExplainService:
    """Explain a staging item against the catalog context."""

    def __init__(self, explainer: Explainer) -> None:
        self._explainer = explainer

    async def explain(
        self,
        item: StagingItem,
        catalog: Optional[CatalogSnapshot] = None,
    ) -> StagingItem:
        request = ExplainRequest(item=item, catalog=catalog)
        explanation = await self._explainer.explain(request)
        return self._apply(item, explanation)

    def _apply(self, item: StagingItem, explanation: Explanation) -> StagingItem:
        evidence = item.evidence.model_copy(update={"explanation": explanation})
        updated = item.model_copy(update={"evidence": evidence})
        return updated.transition_to(State.ENRICHED)


def _evidence_present(*, item_text: str, item: StagingItem) -> bool:
    """The quoted evidence must appear in the stem or the passage."""
    needle = item_text.strip()
    if not needle:
        return False
    haystacks = [item.content.stem.text]
    for option in item.content.options:
        haystacks.append(option.text.text)
    if item.passage is not None:
        haystacks.append(item.passage.text.text)
    return any(needle in hay for hay in haystacks)
