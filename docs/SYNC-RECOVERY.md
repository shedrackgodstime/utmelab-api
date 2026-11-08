# Sync Replica Recovery

The local replica is a serving copy. A damaged copy must be quarantined before
the service builds a replacement. The service never deletes the damaged file.

## Automatic recovery

When the sync engine reports a corrupt or invalid database, the supervisor:

1. Records the build failure.
2. Renames the replica and any `-wal` or `-shm` sidecars with a
   `.corrupt-<timestamp>-<pid>` suffix.
3. Starts a fresh remote build.
4. Pulls and verifies the replacement before data routes become ready.

Permission errors, disk-full errors, authentication failures, and connection
failures are not treated as corruption. They remain visible as blocked sync
states and are not renamed automatically.

## Operator checks

Check the admin sync status and service logs first. Look for
`sync_replica_quarantined` or `sync_replica_quarantine_failed`.

Keep the quarantined file until the incident is understood. It may contain
evidence needed for diagnosis. Confirm that the replacement reaches ready
state before removing any old replica artifacts.

If the replacement cannot start, check disk space, file ownership, the
configured `REPLICA_PATH`, and the Turso URL and token. Do not manually delete
the serving replica while the service is running.

## Recovery boundary

The automatic path handles local database corruption detected during build. It
does not repair schema mismatches, remote authentication, bad configuration,
or a full disk. Those conditions require an operator fix followed by the
supervisor's next probe or a controlled restart.
