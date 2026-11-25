# Sync Replica Recovery

The local replica is a serving copy. A damaged copy must be quarantined before
the service builds a replacement. The service never deletes the damaged file.

## Automatic recovery

When the sync engine reports a corrupt or invalid database, the supervisor:

1. Records the build failure.
2. Renames the replica and its `-wal`, `-shm`, `-log`, `-changes`, `-info`, and
   `-wal-revert` sidecars with a `.corrupt-<timestamp>-<nanos>-<pid>` suffix.
3. Starts a fresh remote build.
4. Pulls and verifies the replacement before data routes become ready.

Permission errors, disk-full errors, authentication failures, and connection
failures are not treated as corruption. They remain visible as blocked sync
states and are not renamed automatically.

## Operator-triggered full resync

`POST /api/internal/admin/sync/resync` asks the supervisor to rebuild the
replica now. The route requires an admin session. The same operation is mounted
as the `resync_now` tool on `/mcp/admin` for an admin key with `manage:keys`.
That mirror exists because the internal route is not exposed through the public
proxy and an operator may not have SSH access. Both surfaces call the same
store function, which enforces one operator gate. The gate is closed unless the
running process has `SYNC_RESYNC_ENABLED=1`. A gated refusal returns
`{"error": "...", "code": "conflict"}` with HTTP 409 or the MCP `conflict`
code. Both surfaces return `{"ok": true}` when a rebuild is queued and
`{"ok": false}` when a rebuild is already queued. The call returns before the
rebuild finishes.

The rebuild is drain-first and staged. At request time the supervisor pauses
new writes, then waits for pending local work to reach Turso. Reads keep using
the serving replica. The wait is bounded by `SYNC_RESYNC_DRAIN_SECS`, which
defaults to 120. A drain that cannot finish aborts the operation and leaves the
serving replica and queued work untouched. Only after the drain succeeds does
the supervisor advance the rebuild epoch, retire the old sync root, build a
fresh replica at a `.resync-<epoch>-<pid>` path, pull from Turso, and verify the
schema contract there. Only a verified candidate reaches the swap. The swap
takes the write lock, retires pooled connections, renames the serving replica
and all sidecars with `.resync-superseded-`, promotes the staged artifacts,
reopens them at `REPLICA_PATH`, refreshes caches, and clears pending write
counters. Writes resume after that point. A failed candidate or failed swap
restores the displaced files and the old connection pool. No process restart is
needed.

Set `SYNC_RESYNC_ENABLED=1` only for an operator rebuild. A full resync does
not discard committed local work: it waits for that work to reach Turso first.
Use it when the serving copy is stale or wrong and cloud holds the truth. Never
use it for migration between databases. Check `sync_resync_enabled`,
`sync_resync_pending`, and `sync_resync_draining` before and after the call. The
`status` tool on `/mcp/admin` returns the same admin status with an admin key,
which is the reachable path when the session route is not.

## Operator checks

Check the admin sync status and service logs first. Look for
`sync_resync_requested`, `sync_resync_drain_started`,
`sync_resync_drain_complete`, `sync_resync_started`, `sync_resync_swapped`, and
`sync_resync_complete`. A rejected request leaves a `conflict` event out of the
logs and leaves `sync_resync_pending` false. A drain that could not finish logs
`sync_resync_drain_timeout` or `sync_resync_drain_aborted`, followed by
`sync_resync_aborted`, and leaves the serving replica and pending work intact.
A failed rebuild logs `sync_resync_stage_not_verified`,
`sync_resync_promote_failed`, `sync_resync_final_build_failed`, or
`sync_resync_rollback`.

Keep the quarantined file until the incident is understood. It may contain
evidence needed for diagnosis. Confirm that the replacement reaches ready
state before removing any old replica artifacts. Failed candidates are kept
with a `.resync-failed-` suffix and displaced serving files with a
`.resync-superseded-` suffix.

If the replacement cannot start, check disk space, file ownership, the
configured `REPLICA_PATH`, and the Turso URL and token. Do not manually delete
the serving replica while the service is running.

## Recovery boundary

The automatic path handles local database corruption detected during build.
The operator endpoint handles a stuck replica cursor or a serving copy that no
longer matches cloud. Neither path repairs schema mismatches, remote
authentication, bad configuration, or a full disk. Those conditions require an
operator fix followed by the supervisor's next probe or a controlled restart.
