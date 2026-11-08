# ADR 0004: Write Admission and Idempotency

## Decision

Local writes are admitted against bounded pending-work limits. Key creation
accepts an `Idempotency-Key`; the database stores only its hash and rejects a
reused request key.

## Consequences

An outage cannot grow the local change log without limit, and a lost response
cannot cause a client retry to mint another key.

## Enforcement

`src/store/write.rs` owns admission. `api_keys.idempotency_hash` has a unique
constraint. Account and schema tests cover retry behavior and migration.
