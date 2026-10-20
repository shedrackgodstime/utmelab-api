"""The allowed state transitions. This is the only source of truth."""

from types import MappingProxyType
from typing import Mapping

from .enums import State

TERMINAL_STATES = frozenset({State.READY, State.REJECTED, State.FAILED})

TRANSITIONS: Mapping[State, frozenset[State]] = MappingProxyType(
    {
        State.PLANNED: frozenset({State.ACQUIRED, State.REJECTED, State.FAILED}),
        State.ACQUIRED: frozenset({State.ADAPTED, State.REJECTED, State.FAILED}),
        State.ADAPTED: frozenset({State.GATED, State.REJECTED, State.FAILED}),
        State.GATED: frozenset({State.DEDUPED, State.REJECTED, State.FAILED}),
        State.DEDUPED: frozenset({State.CATALOGUED, State.REJECTED, State.FAILED}),
        State.CATALOGUED: frozenset(
            {State.MEDIA_READY, State.ENRICHED, State.REJECTED, State.FAILED}
        ),
        State.MEDIA_READY: frozenset({State.DESCRIBED, State.REJECTED, State.FAILED}),
        State.DESCRIBED: frozenset({State.ENRICHED, State.REJECTED, State.FAILED}),
        State.ENRICHED: frozenset({State.VERIFIED, State.REJECTED, State.FAILED}),
        State.VERIFIED: frozenset({State.READY, State.REJECTED, State.FAILED}),
        State.READY: frozenset(),
        State.REJECTED: frozenset(),
        State.FAILED: frozenset(),
    }
)


class InvalidTransition(ValueError):
    """Raised when a caller tries a transition the pipeline does not allow."""


def next_states(state: State) -> frozenset[State]:
    return TRANSITIONS[state]


def can_transition(source: State, target: State) -> bool:
    return target in TRANSITIONS[source]


def assert_transition(source: State, target: State) -> None:
    if not can_transition(source, target):
        raise InvalidTransition(f"cannot move from {source.value} to {target.value}")
