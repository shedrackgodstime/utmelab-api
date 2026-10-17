# Prototyping notes (throwaway)

Isolated Rust project. No link to `src/`. Judge in `debug` only, no `--release`.

## Goals
1. Axum serving max consumers on low RAM (1.5-2GB target).
2. Turso read path staying fast (next).

## Config (env)
- `WORKER_THREADS` default 4
- `MAX_BLOCKING_THREADS` default 32 (was Tokio default 512, too much stack for 1.5GB)
- `CONCURRENCY_LIMIT` default 1000
- `PORT` default 3100

Example: `WORKER_THREADS=$(nproc) cargo run` for dev box, `WORKER_THREADS=2` for small prod.

## Decisions
- Stateless handlers: `/health` returns `&'static str`, `/json` tiny struct. No alloc per request.
- Shared state via `Arc<str>` + `FromRef` substate (`NameOnly`), hot path never sees DB handle.
- Never block workers: async sleep for IO wait, `spawn_blocking` only for CPU (`/cpu`).
- Layers: `RequestBodyLimit(16KB)` + `Timeout(5s, 408)` + `ConcurrencyLimit` for backpressure. Compression only on big route (`/cpu`), not global. `Trace` kept for now.
- Allocator: `mimalloc` to avoid retained RSS after bursts.
- `serde_json` kept. `sonic-rs` skipped: only matters for large payloads (>few KB), needs custom extractor + arch-specific SIMD.

## Bench (debug, `wrk -t4 -c200 -d20s`)
v1 (default runtime):
- `/health`: 58.3k req/s, 3.42ms
- `/json`: 53.0k req/s, 3.76ms
- `/slow` (50ms sleep): 3.8k req/s, 52ms

v2 (workers=4, blocking=32, limit=1000, mimalloc, no global gzip):
- `/health`: 32.5k req/s, 6.17ms
- `/json`: 33.4k req/s, 5.97ms
- `/slow`: 3.8k req/s, 52ms (unchanged, capped by Little's law: 200/0.05 = 4k max)
- `/cpu`: 5.4k req/s, 36ms

Read: v2 slower on big dev box because 4 workers < nproc. Trade is bounded RAM for 1.5GB target. `/slow` proving handler cost dominates Axum overhead.

## Next
- Turso compare: `remote` vs `replica` read latency, same `wrk` method.
- Rule going in: remote per-query round trip behaves like `/slow`, local file reads behave like `/health`.

## Turso decision
- Lib: `turso v0.8` with `sync` for local reads + `libsql v0.10` for remote baseline. NOT `libsql` embedded replicas.
- Why: `libsql` replica (`new_remote_replica`) failed on this DB with `file is not a database` even fresh. New-engine DB speaks CDC sync, not page replication. `turso::sync::Builder` + `pull()`/`push()` is the matching client.
- `sync.db` is disposable cache. Delete anytime, `bootstrap_if_empty(true)` + `pull()` refetches.
- Freshness: background `pull()` every `SYNC_SECS=60`. Allocator: `turso` sets its own, our `mimalloc` removed. Trace `on_failure` lowered ERROR -> WARN.

## Turso bench (debug, real cloud DB ap-south-1)
- Single query: `/db-sync` 7ms local vs `/db-remote` 1600-2050ms network. Sync wins 200x+.
- `/db-sync` reports 5 tables vs `/db-remote` 1 table: local file includes internal sync bookkeeping tables. Cosmetic only.
- Burst problem: under `wrk -c200`, sync queries 502 in ~10ms and 4-worker runtime wedges (even `/health` stalls). Hypothesis: turso connect/query blocks or serializes workers. Fix to prototype: semaphore-gated DB access (e.g. 16 permits) + fast 503 when saturated, so bursts queue async instead of starving workers.
- Remote under burst: 31 req/s at -c50, 0 completions at -c20 after hammering (5s TimeoutLayer eats everything). Remote-only rejected again.

## Gate bench (`DB_MAX_CONCURRENT=16`, try_acquire else fast 503)
- `-c50`: 172 req/s, 277ms avg, 6 non-2xx. No wedge, `/health` alive right after.
- `-c200`: 200 req/s, 932ms avg, 2 non-2xx + 29 wrk timeouts (queue tail >2s). No 502 storm (8 total), no crash.
- Cost: burst queueing delays everything on 4 workers; `/health` curl during/after -c200 timed out at 8s. Gate prevents death, not latency. Options: `DB_MAX_CONCURRENT=8`, or health on separate port/listener.
- RAM after 99s incl. bursts: ~90MB flat. Fits 1.5GB with big margin.
