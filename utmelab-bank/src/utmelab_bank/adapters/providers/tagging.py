"""Tag and explain capabilities. The core validates, the model proposes."""

from __future__ import annotations

from utmelab_bank.domain.capabilities import ExplainRequest, TagRequest
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import (
    CatalogRef,
    CatalogSnapshot,
    Explanation,
    StagingItem,
    TagProposal,
)
from utmelab_bank.domain.ports import Explainer, Tagger


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
        return self._apply(item, proposal, catalog)

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

    def _apply(
        self,
        item: StagingItem,
        proposal: TagProposal,
        catalog: CatalogSnapshot,
    ) -> StagingItem:
        """Record the placement the catalog just accepted.

        A source that does not read the catalog arrives with no placement.
        The tag step is the catalogue step, so this is where the placement is
        created, using the row's own scope and the catalog version the choice
        was validated against. A source that already supplied one keeps its
        shape and gets the accepted ids and the current version.
        """
        evidence = item.evidence.model_copy(update={"tag": proposal})
        if item.catalog is not None:
            placement = item.catalog.model_copy(
                update={
                    "topic_id": proposal.topic_id,
                    "subtopic_id": proposal.subtopic_id,
                    "catalog_version": catalog.version,
                }
            )
        else:
            scope = item.provenance.scope
            placement = CatalogRef(
                exam=scope.exam,
                subject=scope.subject,
                year=scope.year,
                section=scope.section,
                topic_id=proposal.topic_id,
                subtopic_id=proposal.subtopic_id,
                catalog_version=catalog.version,
            )
        updated = item.model_copy(update={"evidence": evidence, "catalog": placement})
        return updated.transition_to(State.CATALOGUED)


class ExplainService:
    """Explain a staging item against the catalog context."""

    def __init__(self, explainer: Explainer) -> None:
        self._explainer = explainer

    async def explain(
        self,
        item: StagingItem,
        catalog: CatalogSnapshot | None = None,
    ) -> StagingItem:
        request = ExplainRequest(item=item, catalog=catalog)
        explanation = await self._explainer.explain(request)
        return self._apply(item, explanation)

    def _apply(self, item: StagingItem, explanation: Explanation) -> StagingItem:
        evidence = item.evidence.model_copy(update={"explanation": explanation})
        # The explanation is part of the content fingerprint, so adding it
        # changes the hash a verification is written against. Re-stamp first.
        updated = item.model_copy(update={"evidence": evidence}).stamp_hashes()
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
