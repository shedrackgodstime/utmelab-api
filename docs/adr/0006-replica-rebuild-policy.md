# ADR 0006: Replica Rebuild Policy

## Decision

Only a clearly invalid local SQLite replica is quarantined automatically. The
file and its `-wal`, `-shm`, `-log`, `-changes`, `-info`, and `-wal-revert`
sidecars are renamed with a timestamp, nanosecond, and process suffix. The
service then builds a fresh replica from Turso.

An admin may request a rebuild without a restart through
`POST /api/internal/admin/sync/resync` or the `resync_now` tool on `/mcp/admin`.
Both surfaces call one store function behind their own gates, and that function
enforces `SYNC_RESYNC_ENABLED`. The gate defaults to false because the operation
discards local work and is not a migration tool. The keyed mirror keeps the
control reachable when the internal route sits behind the proxy and SSH is
unavailable. The request is single-flight and does not disturb the serving
replica. The supervisor aborts the current root, builds and verifies a candidate
at a staged path, then swaps it in under the write lock. The swap retires
connections, quarantines the displaced files, promotes the staged artifacts,
and refreshes caches. A failed candidate or failed swap restores the old files
and pool. Quarantined files are kept for diagnosis.

## Consequences

Corrupt or stale local state can be replaced while the process stays up. The
verification work runs off to the side, so readers keep using the old replica
until a verified replacement exists. The swap itself is short and serialized
with writes. Local commits that have not reached Turso are discarded by an
operator-triggered resync, so cloud must be the source of truth. Permission,
disk, credential, and schema failures remain visible for operator action.

## Enforcement

`src/store/sync.rs` checks the SQLite header, classifies engine corruption,
quarantines every replica artifact, stages operator rebuilds, and logs each
event. The admin route is session-gated. The MCP tool needs `manage:keys`. Both
reach the same gated store function, and a source tripwire forbids a direct call
to the raw state request outside the sync module. The `status` tool on
`/mcp/admin` mirrors the session status route so an operator can watch the gate
and pending flag from the keyed surface. Recovery tests and
`docs/SYNC-RECOVERY.md` define the operator boundary.
