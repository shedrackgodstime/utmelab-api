"""Contract tests for the review step and the audit.

The review is the step that lets the bank produce content at volume, so
what it records matters: the kind, the scope, the model, the reason, and
the hash of the content as it stands.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from utmelab_bank.adapters.audit_service import AuditService
from utmelab_bank.adapters.review_service import ReviewFailed, ReviewService
from utmelab_bank.domain.audit import agreement
from utmelab_bank.domain.enums import State, VerificationKind, Verdict
from utmelab_bank.domain.models import (
    AnswerVerdict,
    Content,
    Hashes,
    Option,
    Producer,
    Provenance,
    RichText,
    Scope,
    StagingItem,
    Verification,
)

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
HASH = "c" * 64


def make_item(
    *,
    item_id: str = "live:q1",
    state: State = State.ENRICHED,
    with_hash: bool = True,
) -> StagingItem:
    provenance = Provenance(
        source="live",
        source_url="https://example.com/q1",
        source_item_id=item_id.split(":")[-1],
        fetched_at=NOW,
        payload_hash="b" * 64,
        source_version="1",
        scope=Scope(exam="JAMB", subject="mathematics", year=2025),
    )
    content = Content(
        stem=RichText(text="What is 2 + 2?"),
        options=(
            Option(id="a", text=RichText(text="3")),
            Option(id="b", text=RichText(text="4")),
            Option(id="c", text=RichText(text="5")),
            Option(id="d", text=RichText(text="6")),
        ),
        answer="b",
        marks=1.0,
        source_explanation=RichText(text="Two and two is four."),
    )
    return StagingItem(
        id=item_id,
        provenance=provenance,
        content=content,
        state=state,
        hashes=(
            Hashes(payload_hash="b" * 64, content_hash=HASH, bundle_hash="d" * 64)
            if with_hash
            else None
        ),
        created_at=NOW,
        updated_at=NOW,
    )


class FakeVerifier:
    """A verifier that returns a fixed verdict."""

    def __init__(self, verdict: Verdict = Verdict.PASS) -> None:
        self.verdict = verdict
        self.calls = 0
        self.producer = Producer(provider="opencode", model="nemotron-3-ultra")

    async def verify(self, request: Any) -> AnswerVerdict:
        self.calls += 1
        return AnswerVerdict(
            verdict=self.verdict,
            reasoning="The arithmetic is right and the explanation teaches it.",
            confidence=0.9,
            producer=self.producer,
        )


# ── the review ──────────────────────────────────────────────────────────────


async def test_a_passing_review_moves_the_item_to_verified() -> None:
    service = ReviewService(FakeVerifier(Verdict.PASS))

    moved = await service.apply(make_item())

    assert moved.state is State.VERIFIED
    assert moved.error is None


async def test_a_failing_review_refuses_the_item_with_the_reason() -> None:
    service = ReviewService(FakeVerifier(Verdict.FAIL))

    refused = await service.apply(make_item())

    assert refused.state is State.REJECTED
    assert refused.error is not None
    assert "review_fail" in refused.error
    assert "arithmetic" in refused.error


async def test_an_abstaining_review_refuses_the_item() -> None:
    service = ReviewService(FakeVerifier(Verdict.ABSTAIN))

    refused = await service.apply(make_item())

    assert refused.state is State.REJECTED
    assert refused.error is not None
    assert "review_abstain" in refused.error


async def test_the_review_records_the_kind_scope_model_and_reason() -> None:
    service = ReviewService(FakeVerifier(Verdict.PASS), bulk=False)

    outcome = await service.review(make_item())
    record = outcome.record

    assert record.kind is VerificationKind.AI_SINGLE
    assert record.scope == ("answer", "explanation", "topic_link")
    assert record.reviewer == "nemotron-3-ultra"
    assert record.producer is not None
    assert record.producer.provider == "opencode"
    assert record.note is not None
    assert "arithmetic" in record.note


async def test_a_bulk_run_is_a_different_kind_from_a_single_check() -> None:
    item = make_item()

    bulk = await ReviewService(FakeVerifier(), bulk=True).review(item)
    single = await ReviewService(FakeVerifier(), bulk=False).review(item)

    assert bulk.record.kind is VerificationKind.AI_BULK
    assert single.record.kind is VerificationKind.AI_SINGLE


async def test_the_record_carries_the_hash_of_the_content_as_it_stands() -> None:
    service = ReviewService(FakeVerifier())

    outcome = await service.review(make_item())

    assert outcome.record.content_hash == HASH


async def test_the_record_is_kept_on_the_item() -> None:
    service = ReviewService(FakeVerifier())

    moved = await service.apply(make_item())

    assert len(moved.evidence.verifications) == 1
    assert moved.evidence.verifications[0].kind is VerificationKind.AI_BULK
    assert moved.evidence.answer_verdict is not None
    assert moved.evidence.answer_verdict.verdict is Verdict.PASS


async def test_a_row_with_no_hash_cannot_be_reviewed() -> None:
    service = ReviewService(FakeVerifier())

    with pytest.raises(ReviewFailed, match="no content hash"):
        await service.review(make_item(with_hash=False))


# ── the audit ───────────────────────────────────────────────────────────────


def reviewed_item(item_id: str, verdict: Verdict) -> StagingItem:
    """An item that carries one verification with a given verdict."""
    item = make_item(item_id=item_id)
    record = Verification(
        id=f"{item_id}:ai_bulk",
        kind=VerificationKind.AI_BULK,
        verdict=verdict,
        scope=("answer", "explanation", "topic_link"),
        content_hash=HASH,
        reviewer="nemotron-3-ultra",
        created_at=NOW,
        producer=Producer(provider="opencode", model="nemotron-3-ultra"),
    )
    evidence = item.evidence.model_copy(
        update={"verifications": (record,)}
    )
    return item.model_copy(update={"evidence": evidence})


def test_the_agreement_rate_is_measured() -> None:
    """The machine passed the second row and the person did not.

    That is a miss, and it is counted apart from the rows they agreed on,
    because it is the direction that lets wrong content through.
    """
    result = agreement(
        [Verdict.PASS, Verdict.PASS, Verdict.FAIL, Verdict.PASS],
        [Verdict.PASS, Verdict.FAIL, Verdict.FAIL, Verdict.PASS],
    )

    assert result.checked == 4
    assert result.agreed == 3
    assert result.missed == 1
    assert result.over_strict == 0
    assert result.rate == 0.75
    assert result.miss_rate == 0.25


def test_a_miss_is_counted_separately_from_an_over_strict() -> None:
    """A pass the person failed is the dangerous direction."""
    result = agreement([Verdict.PASS], [Verdict.FAIL])

    assert result.missed == 1
    assert result.over_strict == 0
    assert result.miss_rate == 1.0


def test_an_abstention_agrees_only_with_an_abstention() -> None:
    both = agreement([Verdict.ABSTAIN], [Verdict.ABSTAIN])
    mixed = agreement([Verdict.ABSTAIN], [Verdict.PASS])

    assert both.agreed == 1
    assert mixed.agreed == 0
    assert mixed.over_strict == 1


def test_an_empty_sample_has_no_rate() -> None:
    result = agreement([], [])

    assert result.checked == 0
    assert result.rate == 0.0
    assert "no sample" in str(result)


def test_two_different_lengths_are_refused() -> None:
    with pytest.raises(ValueError, match="checked"):
        agreement([Verdict.PASS], [Verdict.PASS, Verdict.FAIL])


def test_the_sample_is_deterministic() -> None:
    items = [reviewed_item(f"live:q{index}", Verdict.PASS) for index in range(10)]
    service = AuditService(items)

    first = service.sample(3)
    second = service.sample(3)

    assert [item.id for item in first] == [item.id for item in second]
    assert len(first) == 3


def test_the_sample_covers_the_whole_run() -> None:
    items = [reviewed_item(f"live:q{index}", Verdict.PASS) for index in range(10)]
    service = AuditService(items)

    sample = service.sample(3)

    assert sample[0].id == "live:q0"
    assert sample[-1].id == "live:q9"


def test_a_sample_larger_than_the_run_is_the_run() -> None:
    items = [reviewed_item(f"live:q{index}", Verdict.PASS) for index in range(3)]
    service = AuditService(items)

    assert len(service.sample(10)) == 3


def test_the_measure_uses_the_last_verification() -> None:
    items = [reviewed_item("live:q1", Verdict.PASS)]
    service = AuditService(items)

    result = service.measure(items, [Verdict.FAIL])

    assert result.missed == 1
