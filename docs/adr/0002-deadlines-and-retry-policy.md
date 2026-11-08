# ADR 0002: Deadlines and Retry Policy

## Decision

Every engine operation uses a named budget. Typed failures are classified once,
then retried with bounded backoff and jitter. Permanent classes use a slow
probe and block readiness.

## Consequences

A stalled remote cannot hold a service lock forever. The service does not
create a fast retry storm for invalid credentials or bad configuration.

## Enforcement

`src/store/sync/engine.rs` requires budgets. `src/store/sync/policy.rs` owns
classification and delay decisions. The policy and failure-matrix tests cover
the rules. Turso's current public error surface does not expose `Retry-After`,
so the service does not claim to honor that header yet.
