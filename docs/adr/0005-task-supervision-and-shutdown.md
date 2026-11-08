# ADR 0005: Task Supervision and Shutdown

## Decision

The sync root and push loop are owned by a retained supervisor. Heartbeat age
detects silent failure. Shutdown stops new work, joins the supervisor within a
budget, and attempts one final bounded push when work is pending.

## Consequences

A dead background task becomes visible and recoverable. Shutdown has an
explicit outcome instead of relying on runtime task cancellation.

## Enforcement

`src/store/sync.rs` owns task handles, heartbeat checks, restart behavior, and
shutdown. Supervisor, state, and shutdown tests cover the transitions.
