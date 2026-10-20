from itertools import pairwise

import pytest

from utmelab_pipeline.domain.enums import State
from utmelab_pipeline.domain.state import (
    TERMINAL_STATES,
    TRANSITIONS,
    InvalidTransition,
    assert_transition,
    can_transition,
    next_states,
)

HAPPY_PATH = (
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


def test_every_state_has_an_entry() -> None:
    assert set(TRANSITIONS) == set(State)


def test_happy_path() -> None:
    for source, target in pairwise(HAPPY_PATH):
        assert_transition(source, target)


def test_media_is_optional() -> None:
    assert can_transition(State.CATALOGUED, State.ENRICHED)


def test_terminal_states_have_no_exits() -> None:
    for state in TERMINAL_STATES:
        assert next_states(state) == frozenset()


def test_ready_cannot_move() -> None:
    with pytest.raises(InvalidTransition, match="ready"):
        assert_transition(State.READY, State.PLANNED)


def test_cannot_skip_to_ready() -> None:
    with pytest.raises(InvalidTransition):
        assert_transition(State.PLANNED, State.READY)


def test_failure_is_reachable_from_every_active_state() -> None:
    for state in set(State) - TERMINAL_STATES:
        assert State.FAILED in next_states(state)


def test_gate_can_reject() -> None:
    assert can_transition(State.GATED, State.REJECTED)
    assert can_transition(State.ENRICHED, State.REJECTED)
