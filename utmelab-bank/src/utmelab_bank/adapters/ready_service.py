"""The ready service. Check the bundle against the eight conditions.

Each condition is one function that looks at one row and says why it is not
met, or says nothing when it is. The service runs them over the bundle and
counts.

The conditions are the bank's own. The human sign-off is not one of them,
because the bank cannot give it, so the report counts it separately and the
person decides what to do with the number.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from utmelab_bank.domain.enums import State, VerificationKind
from utmelab_bank.domain.hashing import content_fingerprint
from utmelab_bank.domain.models import (
    CatalogSnapshot,
    StagingItem,
)
from utmelab_bank.domain.ready import (
    ConditionReport,
    ReadyBundle,
    ReadyCondition,
    ReadyReport,
)


@dataclass(frozen=True)
class ReadyContext:
    """What the checks need to know beyond the row itself.

    The catalog is the authority for placement, and the known passage ids are
    what the bank already holds.
    """

    catalog: CatalogSnapshot | None = None
    known_passage_ids: frozenset[str] = field(default_factory=frozenset)


#: What a check returns: None when the row meets the condition, and the
#: reason when it does not.
Check = Callable[[StagingItem, ReadyContext], str | None]


def _gated(item: StagingItem, context: ReadyContext) -> str | None:
    verdict = item.evidence.gate
    if verdict is None:
        return "the gate did not run"
    if not verdict.passed:
        codes = ", ".join(sorted({issue.code for issue in verdict.issues}))
        return f"the gate refused it: {codes}"
    return None


def _reviewed(item: StagingItem, context: ReadyContext) -> str | None:
    """A check that covers the answer and the explanation, at this hash.

    The hash matters. A check made against content that has since changed
    does not cover the content as it stands.

    The check may be a machine's or a person's. How many of them are a
    person's is counted separately, because the serving predicate counts
    only a person and the bank cannot raise that number.
    """
    if item.hashes is None or not item.hashes.content_hash:
        return "there is no content hash to check against"
    for record in reversed(item.evidence.verifications):
        scope = set(record.scope)
        if "answer" in scope and "explanation" in scope:
            if record.content_hash != item.hashes.content_hash:
                return "the check covered content that has since changed"
            return None
    return "no check covers the answer and the explanation"


def _placed(item: StagingItem, context: ReadyContext) -> str | None:
    placement = item.catalog
    if placement is None:
        return "there is no placement"
    if not placement.subtopic_id or not placement.topic_id:
        return "the placement names no subtopic"
    catalog = context.catalog
    if catalog is None:
        return None
    if catalog.exam != placement.exam or catalog.subject != placement.subject:
        return (
            f"the catalog is for {catalog.subject!r} for {catalog.exam!r}, not "
            f"{placement.subject!r} for {placement.exam!r}"
        )
    subtopic = next((s for s in catalog.subtopics if s.id == placement.subtopic_id), None)
    if subtopic is None:
        return f"the subtopic {placement.subtopic_id!r} is not in the catalog"
    if subtopic.topic_id != placement.topic_id:
        return (
            f"the subtopic {placement.subtopic_id!r} sits under "
            f"{subtopic.topic_id!r}, not {placement.topic_id!r}"
        )
    topic = next((t for t in catalog.topics if t.id == placement.topic_id), None)
    if topic is None:
        return f"the topic {placement.topic_id!r} is not in the catalog"
    return None


def _complete(item: StagingItem, context: ReadyContext) -> str | None:
    content = item.content
    if not content.stem.text.strip():
        return "the stem is empty"
    if len(content.options) < 2:
        return "there are fewer than two options"
    ids = {option.id for option in content.options}
    if content.answer not in ids:
        return "the answer names none of the options"
    if not 0.5 <= content.marks <= 10.0:
        return "the marks are outside the accepted range"
    return None


def _explanatory(item: StagingItem, context: ReadyContext) -> str | None:
    explanation = item.evidence.explanation
    if explanation is None:
        return "there is no explanation"
    if not explanation.key_point.text.strip():
        return "the explanation has no key point"
    if not explanation.body.text.strip():
        return "the explanation has no body"
    return None


def _resolvable(item: StagingItem, context: ReadyContext) -> str | None:
    passage_id = item.content.passage_id
    if (
        passage_id is not None
        and item.passage is None
        and passage_id not in context.known_passage_ids
    ):
        return f"the passage {passage_id!r} is not held"
    for inline in item.content.stem.inline:
        if inline.kind.value == "image":
            if not inline.url:
                return "a figure has no url"
            if inline.position is None:
                return "a figure has no position"
    return None


def _identified(item: StagingItem, context: ReadyContext) -> str | None:
    """The hash must match the content as it stands.

    This is the check that catches an edit made after the check, and it is
    the one that keeps a bundle honest.
    """
    if item.hashes is None or not item.hashes.content_hash:
        return "there is no content hash"
    current = content_fingerprint(
        stem=item.content.stem,
        options=item.content.options,
        answer=item.content.answer,
        explanation=item.evidence.explanation,
    )
    if current != item.hashes.content_hash:
        return "the content has changed since the hash was stamped"
    return None


def _new(item: StagingItem, context: ReadyContext) -> str | None:
    """The row must carry a hash, and the dedupe step has already run.

    The near-duplicate check belongs to the dedupe step, and it has already
    refused anything that duplicates what the bank holds.
    """
    if item.hashes is None or not item.hashes.content_hash:
        return "there is no content hash"
    return None


#: The eight checks, in the order they are reported.
CHECKS: tuple[tuple[ReadyCondition, Check], ...] = (
    (ReadyCondition.GATED, _gated),
    (ReadyCondition.REVIEWED, _reviewed),
    (ReadyCondition.PLACED, _placed),
    (ReadyCondition.COMPLETE, _complete),
    (ReadyCondition.EXPLANATORY, _explanatory),
    (ReadyCondition.RESOLVABLE, _resolvable),
    (ReadyCondition.IDENTIFIED, _identified),
    (ReadyCondition.NEW, _new),
)


class ReadyService:
    """Checks a bundle against the eight conditions and reports."""

    def __init__(
        self,
        *,
        catalog: CatalogSnapshot | None = None,
        known_passage_ids: Iterable[str] = (),
    ) -> None:
        self._context = ReadyContext(
            catalog=catalog,
            known_passage_ids=frozenset(known_passage_ids),
        )

    def check(self, items: Iterable[StagingItem]) -> ReadyReport:
        """Check every row and report condition by condition."""
        rows = tuple(items)
        reports: list[ConditionReport] = []
        for condition, check in CHECKS:
            met = 0
            reasons: list[str] = []
            for item in rows:
                reason = check(item, self._context)
                if reason is None:
                    met += 1
                elif reason not in reasons:
                    reasons.append(reason)
            reports.append(
                ConditionReport(
                    condition=condition,
                    met=met,
                    unmet=len(rows) - met,
                    reasons=tuple(reasons),
                )
            )
        return ReadyReport(
            conditions=tuple(reports),
            human_signed=self._human_signed(rows),
            total=len(rows),
        )

    def bundle(self, items: Iterable[StagingItem]) -> ReadyBundle:
        """The bundle: the rows, and the report that says where they stand."""
        rows = tuple(items)
        return ReadyBundle(items=rows, report=self.check(rows))

    def promote(self, items: Iterable[StagingItem]) -> ReadyBundle:
        """Move the rows that meet every condition to READY.

        A row is promoted only when all eight checks pass, so a bundle whose
        report is satisfied and a bundle whose rows are READY are the same
        thing. The report is computed over the promoted rows.
        """
        rows = tuple(
            item.transition_to(State.READY)
            if item.state is State.VERIFIED and self._meets_every_condition(item)
            else item
            for item in items
        )
        return self.bundle(rows)

    def _meets_every_condition(self, item: StagingItem) -> bool:
        """Whether one row meets all eight conditions."""
        return all(check(item, self._context) is None for _, check in CHECKS)

    def _human_signed(self, items: tuple[StagingItem, ...]) -> int:
        """How many rows carry a human pass.

        The bank cannot raise this number. The serving predicate counts only
        a human pass, so it is reported rather than required.
        """
        signed = 0
        for item in items:
            for record in item.evidence.verifications:
                if record.kind is VerificationKind.HUMAN:
                    signed += 1
                    break
        return signed


__all__ = ["CHECKS", "ReadyContext", "ReadyService"]
