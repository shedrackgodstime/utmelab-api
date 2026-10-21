"""The allowed state transitions. This is the only source of truth.

The pipeline is a loop, not a line. Content that is already in production can
come back, twice over:

- A **consumer reported it**, so the content is wrong and it is reworked.
- **It drifted**, so what production holds is no longer what the bank
  checked, and the bank redoes it.

Both land back at ``enriched``, because both need the content looked at
again before it is checked again.
"""

from collections.abc import Mapping
from types import MappingProxyType

from .enums import State

TERMINAL_STATES = frozenset({State.REJECTED, State.FAILED})

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
        # The bundle was handed over, so the bank is tracking a live row.
        State.READY: frozenset({State.LIVE, State.REJECTED, State.FAILED}),
        # It is in production and something was said about it.
        State.LIVE: frozenset({State.REPORTED, State.ENRICHED, State.REJECTED, State.FAILED}),
        # A consumer reported it. The content is reworked.
        State.REPORTED: frozenset({State.ENRICHED, State.REJECTED, State.FAILED}),
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
