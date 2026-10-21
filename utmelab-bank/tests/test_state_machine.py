"""Tests for the state machine and the content hash contract."""

import pytest

from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import StagingItem
from utmelab_bank.domain.hashing import content_fingerprint, payload_hash
from utmelab_bank.domain.state import (
    InvalidTransition,
    assert_transition,
    can_transition,
    next_states,
)


def test_every_state_has_a_transition_entry() -> None:
    from utmelab_bank.domain.state import TRANSITIONS

    assert set(TRANSITIONS) == set(State)


def test_happy_path_is_allowed() -> None:
    path = (
        State.PLANNED,
        State.ACQUIRED,
        State.ADAPTED,
        State.GATED,
        State.DEDUPED,
        State.CATALOGUED,
        State.MEDIA_READY,
        State.DESCRIBED,
        State.ENRICHED,
        State.VERIFIED,
        State.READY,
    )
    for source, target in zip(path, path[1:]):
        assert_transition(source, target)


def test_media_step_is_optional() -> None:
    assert can_transition(State.CATALOGUED, State.ENRICHED)


def test_cannot_skip_to_ready() -> None:
    with pytest.raises(InvalidTransition, match="planned to ready"):
        assert_transition(State.PLANNED, State.READY)


def test_terminal_states_have_no_exits() -> None:
    for state in (State.REJECTED, State.FAILED):
        assert next_states(state) == frozenset()


def test_ready_is_not_the_end() -> None:
    """A ready bundle is handed over, so the bank keeps tracking the row."""
    assert can_transition(State.READY, State.LIVE)


def test_a_live_row_can_be_reported() -> None:
    assert can_transition(State.LIVE, State.REPORTED)


def test_a_reported_row_goes_back_to_the_bench() -> None:
    """The content is reworked, so it is looked at again."""
    assert can_transition(State.REPORTED, State.ENRICHED)


def test_a_live_row_can_drift_back_to_the_bench() -> None:
    """The content is fine, but the check on it is stale."""
    assert can_transition(State.LIVE, State.ENRICHED)


def test_the_live_loop_is_a_loop() -> None:
    """Content that is already in production comes back."""
    assert can_transition(State.LIVE, State.REPORTED)
    assert can_transition(State.REPORTED, State.ENRICHED)
    assert can_transition(State.ENRICHED, State.VERIFIED)
    assert can_transition(State.VERIFIED, State.READY)
    assert can_transition(State.READY, State.LIVE)


def test_staging_item_transition_refuses_an_invented_move(staging_item: StagingItem) -> None:
    with pytest.raises(InvalidTransition):
        staging_item.transition_to(State.READY)


def test_staging_item_transition_moves_forward(staging_item: StagingItem) -> None:
    result = staging_item.transition_to(State.ENRICHED)
    assert result.state is State.ENRICHED
    assert result.updated_at >= staging_item.updated_at


def test_payload_hash_is_key_order_independent() -> None:
    assert payload_hash({"b": 2, "a": 1}) == payload_hash({"a": 1, "b": 2})


def test_content_fingerprint_covers_the_answer(staging_item: StagingItem) -> None:
    item = staging_item
    base = content_fingerprint(
        stem=item.content.stem,
        options=item.content.options,
        answer=item.content.answer,
    )
    changed = content_fingerprint(
        stem=item.content.stem,
        options=item.content.options,
        answer="A",
    )
    assert base != changed


def test_content_fingerprint_covers_the_options(staging_item: StagingItem) -> None:
    item = staging_item
    base = content_fingerprint(
        stem=item.content.stem,
        options=item.content.options,
        answer=item.content.answer,
    )
    changed = content_fingerprint(
        stem=item.content.stem,
        options=(item.content.options[0],),
        answer=item.content.answer,
    )
    assert base != changed


def test_content_fingerprint_is_stable(staging_item: StagingItem) -> None:
    item = staging_item
    first = content_fingerprint(
        stem=item.content.stem,
        options=item.content.options,
        answer=item.content.answer,
    )
    second = content_fingerprint(
        stem=item.content.stem,
        options=item.content.options,
        answer=item.content.answer,
    )
    assert first == second


def test_staging_item_stamps_a_content_hash(staging_item: StagingItem) -> None:
    stamped = staging_item.with_content_hash()
    assert stamped.hashes is not None
    assert staging_item.hashes is not None
    assert stamped.hashes.content_hash != staging_item.hashes.content_hash
    # The payload hash is untouched by the content stamp.
    assert stamped.hashes.payload_hash == staging_item.hashes.payload_hash


def test_verification_must_match_the_content_hash(staging_item: StagingItem) -> None:
    from utmelab_bank.domain.enums import VerificationKind, Verdict
    from utmelab_bank.domain.models import Evidence, Verification

    stamped = staging_item.with_content_hash()
    assert stamped.hashes is not None
    good = Verification(
        id="v-1",
        kind=VerificationKind.HUMAN,
        verdict=Verdict.PASS,
        scope=("answer",),
        content_hash=stamped.hashes.content_hash,
        reviewer="human-1",
        created_at=stamped.created_at,
    )
    ok = stamped.model_copy(
        update={"evidence": Evidence(verifications=(good,))}
    )
    assert ok.hashes is not None
    assert ok.evidence.verifications[0].content_hash == ok.hashes.content_hash

    bad = good.model_copy(update={"content_hash": "0" * 64})
    with pytest.raises(ValueError, match="content hash"):
        type(stamped).model_validate(
            {
                **stamped.model_dump(mode="json"),
                "evidence": {"verifications": [bad.model_dump(mode="json")]},
            }
        )


def test_transition_accepts_a_state_name(staging_item: StagingItem) -> None:
    """A caller that holds the name as text still gets the enum back."""
    result = staging_item.transition_to("enriched")  # type: ignore[arg-type]
    assert result.state is State.ENRICHED
    assert result.state.value == "enriched"
