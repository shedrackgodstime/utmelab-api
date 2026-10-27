"""Tag and explain capabilities. The core validates, the model proposes."""

from __future__ import annotations

import logging
from typing import Protocol

from utmelab_bank.domain.capabilities import ExplainRequest, TagRequest
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import (
    CatalogRef,
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
    Explanation,
    StagingItem,
    TagProposal,
)
from utmelab_bank.domain.ports import Explainer, Tagger

_log = logging.getLogger(__name__)

#: A model that copies a long id sometimes stops early. A prefix shorter than
#: this could match a different entry by accident, so only longer ones get the
#: benefit of the doubt, and only when exactly one entry matches.
_MIN_TRUNCATED_ID = 8


class _Identified(Protocol):
    @property
    def id(self) -> str: ...


class UnknownSubtopic(ValueError):
    """Raised when a provider names a subtopic that is not in the snapshot."""


class UnknownTopic(ValueError):
    """Raised when a provider names a topic that is not in the snapshot."""


class LowConfidenceTag(ValueError):
    """Raised when a tag proposal must abstain for human review."""


def _resolve[T: _Identified](
    candidates: tuple[T, ...],
    wanted: str,
    error: type[ValueError],
    kind: str,
) -> T:
    """Find the entry the model meant, refusing to guess between two.

    An exact id always wins. A long, unambiguous prefix is the same id with
    its tail lost in transcription, which happens often with generated slugs.
    Anything shorter or shared by two entries is an unknown reference.
    """
    for candidate in candidates:
        if candidate.id == wanted:
            return candidate
    if len(wanted) >= _MIN_TRUNCATED_ID:
        matches = [c for c in candidates if c.id.startswith(wanted)]
        if len(matches) == 1:
            _log.info("resolved truncated %s id %r to %r", kind, wanted, matches[0].id)
            return matches[0]
        if len(matches) > 1:
            raise error(
                f"provider named {kind} {wanted!r} which matches {len(matches)} "
                "catalog entries, so it is ambiguous"
            )
    raise error(f"provider named {kind} {wanted!r} which is not in the catalog")


class TagService:
    """Tag a row only when its catalog choice and confidence are supported."""

    def __init__(self, tagger: Tagger, *, min_confidence: float = 0.6) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("tag confidence threshold must be between 0 and 1")
        self._tagger = tagger
        self._min_confidence = min_confidence

    async def tag(self, item: StagingItem, catalog: CatalogSnapshot) -> StagingItem:
        request = TagRequest(item=item, catalog=catalog)
        proposal = await self._tagger.tag(request)
        topic, subtopic = self._validate(proposal, catalog, item)
        # The evidence keeps the ids the catalog actually holds, so a truncated
        # reference cannot leave a placement that the review gate later refuses.
        proposal = proposal.model_copy(update={"topic_id": topic.id, "subtopic_id": subtopic.id})
        return self._apply(item, proposal, catalog)

    def _validate(
        self,
        proposal: TagProposal,
        catalog: CatalogSnapshot,
        item: StagingItem,
    ) -> tuple[CatalogTopic, CatalogSubtopic]:
        if proposal.confidence < self._min_confidence:
            raise LowConfidenceTag(
                f"tag confidence {proposal.confidence:.2f} is below "
                f"the {self._min_confidence:.2f} threshold"
            )
        topic = _resolve(catalog.topics, proposal.topic_id, UnknownTopic, "topic")
        subtopic = _resolve(catalog.subtopics, proposal.subtopic_id, UnknownSubtopic, "subtopic")
        if subtopic.topic_id != topic.id:
            raise UnknownSubtopic(f"subtopic {subtopic.id!r} does not belong to topic {topic.id!r}")
        if not _evidence_present(item_text=proposal.evidence, item=item):
            raise ValueError("tag evidence does not appear in the question or passage")
        return topic, subtopic

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
    """The quoted evidence must appear in trusted row text or OCR evidence."""
    needle = _normalise_evidence(item_text)
    if not needle:
        return False
    haystacks = [item.content.stem.text]
    for option in item.content.options:
        haystacks.append(option.text.text)
    if item.passage is not None:
        haystacks.append(item.passage.text.text)
    haystacks.extend(record.text for record in item.evidence.ocr if record.text)
    return any(needle in _normalise_evidence(hay) for hay in haystacks)


def _normalise_evidence(value: str) -> str:
    return " ".join(value.split()).casefold()
