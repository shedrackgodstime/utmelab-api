# UTME Lab API: foundation notes

Working notes for hardening the serving foundation. One entry per known gap,
highest value first. Delete an entry when it is closed.

## Backlog

1. `GET /api/v1/exams/{exam}/papers` costs ~142ms (release) in the per-row
   `verified` predicate. Optimize only if it matters at the expected rate.
2. Consider an adaptive pull interval (longer when the replica is idle) if one
   request per `SYNC_SECS` is judged too chatty.

## Done

- `/api/internal/status` now requires an admin session; `/health` stays the
  public liveness probe.
- Per-key rate limiting on `api` + `mcp`, enforced in the key extractor so no
  route can forget it (`RATE_LIMIT_PER_MIN`, admin unlimited by default). A key
  past its ceiling gets 429 with `Retry-After: 60`.
- Replica WAL/log watched, no action needed: `-wal` stays at 0 (the engine
  checkpoints it) and `-log` moved about 0.3 KB across a full session.
- Graceful shutdown now covers SIGTERM as well as Ctrl-C, so an orchestrator
  stopping the service drains in-flight requests instead of dropping them.
- A schema contract mismatch now fails closed. The sync task had logged
  "refusing to trust replica" while every route still answered; data surfaces
  now answer 503 with code `schema_mismatch`, and `/health` stays independent
  for liveness.

## Decisions worth keeping

- No long poll. Pull on an interval and pool connections, so reads and writes
  never queue behind the sync engine's single IO worker.
- Reads fail fast (5s), writes get cloud headroom (30s), and a global 30s net
  covers any route that forgets its own budget.
- 16KiB request body cap, ~5x the largest body we accept.
- Production code has no `unwrap`/`expect`, no `#[allow]`, no `unsafe`.
