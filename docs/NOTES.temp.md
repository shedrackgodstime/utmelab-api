# UTME Lab API: foundation notes

Working notes for hardening the serving foundation. One entry per known gap,
highest value first. Delete an entry when it is closed.

## Backlog

1. `GET /api/v1/exams/{exam}/papers` costs ~142ms (release) in the per-row
   `verified` predicate. Optimize only if it matters at the expected rate.
2. Consider an adaptive pull interval (longer when the replica is idle) if one
   request per `SYNC_SECS` is judged too chatty.
3. Capacity pass: request telemetry now exists, so run one load test against
   `questions` and `papers` and tune `DB_MAX_CONCURRENT` and `WORKER_THREADS`
   against measured throughput and tail latency instead of guesswork.

## Done

- Admin-only endpoints now live under `/api/internal/admin/*` by convention, and
  `/health` stays the public liveness probe. The operational status moved to
  `/api/internal/admin/status`; the old customer path answers 404.
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
- Liveness and readiness are now distinct: `/health` is liveness, `/ready` is
  200 only once the replica is open and its contract is trusted. A proxy routes
  on `/ready`, so a fail-closed instance leaves rotation instead of answering
  503 to users.
- Request telemetry rides on the admin status: totals by status class, an
  in-flight gauge, and three latency buckets (<25ms, <100ms, >=100ms). Atomics
  only, no DB and no gate; probe routes are excluded so health checks cannot
  drown out real traffic, and 408 counts server-side because it is our timeout.
- Observability foundation: one `obs` vocabulary and audit events on the `audit`
  target (login ok/denied, key create/delete, key revoke/unrevoke, role change).
  Mutations take the acting identity as a required argument and the store is the
  single emit point, so both the HTTP and MCP surfaces are covered and no surface
  can act without an audit line. `audit=info` is forced in the default log filter
  so a bare `warn` fallback cannot swallow a successful key create.

## Decisions worth keeping

- Observability is three separate things: metrics (numbers), logs (events), and
  audit (attributable security and business events). Audit is neither debug
  logging nor metrics; it is its own target so it can be filtered and shipped on
  its own.
- Admin-only endpoints live under `/api/internal/admin/*`; everything else under
  `/api/internal/*` is customer or session.
- No long poll. Pull on an interval and pool connections, so reads and writes
  never queue behind the sync engine's single IO worker.
- Reads fail fast (5s), writes get cloud headroom (30s), and a global 30s net
  covers any route that forgets its own budget.
- 16KiB request body cap, ~5x the largest body we accept.
- Production code has no `unwrap`/`expect`, no `#[allow]`, no `unsafe`.
