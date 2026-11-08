# ADR 0003: Readiness and Staleness

## Decision

Content and credential freshness have separate limits. Public reads may serve
within the content limit. Keyed reads require both limits. Unknown schema,
stalled supervision, and missing verification fail closed.

## Consequences

A temporary auth-data delay cannot silently extend revoked-key acceptance, and
public content can keep serving within its explicit freshness budget.

## Enforcement

`Readiness` in `src/store/sync/state.rs` is the only readiness rule. Health
tests cover stale content, stale auth, and stalled supervision.
