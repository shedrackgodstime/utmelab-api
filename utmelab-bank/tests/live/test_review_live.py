"""A live contract test: the review must work against a real model.

The review is the step that lets the bank produce content at volume, so it
has to work against the model that will do the work. This runs the real
provider on a real question and checks that the verdict comes back, and
that the record carries what the bank needs.

It is skipped unless ``UTMELAB_LIVE=1`` is set, because it needs the model.
"""

from __future__ import annotations

import os

import pytest

from utmelab_bank.adapters.providers.opencode import OpenCodeProvider
from utmelab_bank.adapters.review_service import ReviewService
from utmelab_bank.domain.enums import State, Verdict, VerificationKind
from utmelab_bank.domain.models import StagingItem

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("UTMELAB_LIVE") != "1",
        reason="set UTMELAB_LIVE=1 to run live provider smoke tests",
    ),
]


def _model() -> str:
    return os.environ.get(
        "UTMELAB_OPENCODE_MODEL",
        "opencode/nemotron-3-ultra-free",
    )


async def test_the_review_runs_against_a_real_model(staging_item: StagingItem) -> None:
    provider = OpenCodeProvider(model=_model(), timeout=180.0)
    service = ReviewService(provider, bulk=False)

    outcome = await service.review(staging_item)

    assert outcome.verdict.verdict in (
        Verdict.PASS,
        Verdict.FAIL,
        Verdict.ABSTAIN,
    )
    assert outcome.verdict.reasoning
    assert outcome.record.kind is VerificationKind.AI_SINGLE
    assert outcome.record.scope == ("answer", "explanation", "topic_link")
    assert outcome.record.producer is not None
    assert outcome.record.producer.model == _model()


async def test_the_review_of_a_real_question_moves_the_item(
    staging_item: StagingItem,
) -> None:
    """The review comes after the enrichment, and the state machine says so."""
    provider = OpenCodeProvider(model=_model(), timeout=180.0)
    service = ReviewService(provider, bulk=False)
    enriched = staging_item.transition_to(State.ENRICHED)

    moved = await service.apply(enriched)

    assert moved.state in (State.VERIFIED, State.REJECTED)
    if moved.state is State.REJECTED:
        assert moved.error
