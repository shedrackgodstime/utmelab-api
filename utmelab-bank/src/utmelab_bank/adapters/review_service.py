"""The review service. The machine checks the content, and the check is kept.

This is the step that lets the bank produce content at volume. The gate
judges what a rule can judge, and the review judges what only judgement can:
the answer is right, the explanation teaches, the question is answerable as
written, the topic placement is right.

**The model's verdict is the review, and the review is not the same as a
person's.** Only a human pass makes a row servable, and the production
predicate says so. So what the bank produces here is evidence, and a person
audits it on a sample. The agreement rate from that sample is the number
that decides how much content can move.

Every check is recorded with its kind, its scope, the model that made it and
the reason. A row whose content changes after the check carries a stale
hash, and a stale hash is a check that no longer applies.
"""

from __future__ import annotations

from datetime import UTC, datetime

from utmelab_bank.domain.capabilities import VerifyAnswerRequest
from utmelab_bank.domain.enums import State, Verdict, VerificationKind
from utmelab_bank.domain.models import (
    AnswerVerdict,
    CatalogSnapshot,
    StagingItem,
    Verification,
)
from utmelab_bank.domain.ports import AnswerVerifier
from utmelab_bank.domain.review import REVIEW_SCOPE, review_kind


class ReviewFailed(ValueError):
    """Raised when a check cannot be recorded against the content."""


class ReviewOutcome:
    """What a review found, and the record of the check.

    The verdict is the model's answer. The record is what the bank keeps,
    carrying the kind, the scope, the model and the reason, against the hash
    of the content as it stands.
    """

    __slots__ = ("verdict", "record")

    def __init__(self, verdict: AnswerVerdict, record: Verification) -> None:
        self.verdict = verdict
        self.record = record


class ReviewService:
    """Reviews a staging item and records the check on it."""

    def __init__(
        self,
        verifier: AnswerVerifier,
        *,
        bulk: bool = True,
        min_confidence: float = 0.7,
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("review confidence threshold must be between 0 and 1")
        self._verifier = verifier
        self._kind = review_kind(bulk)
        self._min_confidence = min_confidence

    @property
    def kind(self) -> VerificationKind:
        """The kind of check this service records."""
        return self._kind

    async def review(
        self,
        item: StagingItem,
        catalog: CatalogSnapshot | None = None,
    ) -> ReviewOutcome:
        """Check one item and return the outcome and the record of it.

        The record carries the hash of the content as it stands now, so a
        later edit to the content leaves the check behind, where the
        serving predicate can see it.
        """
        if item.hashes is None or not item.hashes.content_hash:
            raise ReviewFailed("the item has no content hash to check against")

        request = VerifyAnswerRequest(item=item, catalog=catalog)
        verdict = await self._verifier.verify(request)
        if verdict.confidence < self._min_confidence and verdict.verdict is Verdict.PASS:
            verdict = verdict.model_copy(
                update={
                    "verdict": Verdict.ABSTAIN,
                    "reasoning": (
                        f"confidence {verdict.confidence:.2f} is below the "
                        f"{self._min_confidence:.2f} review threshold: {verdict.reasoning}"
                    ),
                }
            )

        record = Verification(
            id=f"{item.id}:{self._kind.value}",
            kind=self._kind,
            verdict=verdict.verdict,
            scope=REVIEW_SCOPE,
            content_hash=item.hashes.content_hash,
            reviewer=verdict.producer.model,
            note=verdict.reasoning,
            producer=verdict.producer,
            created_at=datetime.now(UTC),
        )
        return ReviewOutcome(verdict=verdict, record=record)

    async def apply(
        self,
        item: StagingItem,
        catalog: CatalogSnapshot | None = None,
    ) -> StagingItem:
        """Check one item and move it on or refuse it.

        A row that fails the check is refused, with the reason kept, so the
        failure is visible rather than a silent absence.
        """
        outcome = await self.review(item, catalog)
        record = outcome.record
        if record.verdict is not Verdict.PASS:
            return item.transition_to(
                State.REJECTED,
                error=f"review_{record.verdict.value}: {record.note or ''}".strip(),
            )
        evidence = item.evidence.model_copy(
            update={
                "answer_verdict": outcome.verdict,
                "verifications": item.evidence.verifications + (record,),
            }
        )
        updated = item.model_copy(update={"evidence": evidence})
        return updated.transition_to(State.VERIFIED)


__all__ = ["ReviewFailed", "ReviewOutcome", "ReviewService"]
