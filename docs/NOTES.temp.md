# UTME Lab API: foundation notes

Working notes for hardening the serving foundation. One entry per known gap,
highest value first. Delete an entry when it is closed.

## Backlog

1. Per-key / per-tier rate limiting. Only `login` is limited today. Needed for
   fair use and abuse resistance when many consumers share the API.
2. Replica WAL/log growth. Watch `db/sync-live.db-log` and `-wal` over a long
   run; add a periodic `Database::checkpoint()` only if they grow unbounded.
3. `GET /api/v1/exams/{exam}/papers` costs ~142ms (release) in the per-row
   `verified` predicate. Optimize only if it matters at the expected rate.
4. Consider an adaptive pull interval (longer when the replica is idle) if one
   request per `SYNC_SECS` is judged too chatty.

## Done

- `/api/internal/status` now requires an admin session; `/health` stays the
  public liveness probe.

## Decisions worth keeping

- No long poll. Pull on an interval and pool connections, so reads and writes
  never queue behind the sync engine's single IO worker.
- Reads fail fast (5s), writes get cloud headroom (30s), and a global 30s net
  covers any route that forgets its own budget.
- 16KiB request body cap, ~5x the largest body we accept.
- Production code has no `unwrap`/`expect`, no `#[allow]`, no `unsafe`.
