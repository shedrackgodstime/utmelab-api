# ADR 0006: Replica Rebuild Policy

## Decision

Only a clearly invalid local SQLite replica is quarantined automatically. The
file and sidecars are renamed with a timestamp and process suffix. The service
then builds a fresh replica from Turso.

## Consequences

Corrupt local state can recover without manual deletion, while permission,
disk, credential, and schema failures remain visible for operator action.

## Enforcement

`src/store/sync.rs` checks the SQLite header, classifies engine corruption,
quarantines exact replica files, and logs the event. Recovery tests and
`docs/SYNC-RECOVERY.md` define the operator boundary.
