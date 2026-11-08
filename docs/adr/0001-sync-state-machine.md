# ADR 0001: One Sync State Machine

## Decision

Sync lifecycle state, health facts, readiness, and retry instructions live in
`SyncStatus`. Handlers read the result and do not set readiness flags.

## Consequences

Startup, degradation, blocking, recovery, sleeping, and shutdown have one
shared meaning across HTTP and MCP surfaces.

## Enforcement

`src/store/sync/state.rs` owns the reducer. State and readiness matrix tests,
plus the source tripwires, protect the boundary.
