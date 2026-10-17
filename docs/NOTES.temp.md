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
4. Classify `turso::Error::Busy`/`BusySnapshot` as typed retryable errors before
   `upstream()` stringifies them, instead of text-matching in `is_busy`.
5. Surface `stats()` (pending-change count, WAL size, last push time) read-only
   on the admin status; do not call `checkpoint()` ourselves.

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
  target (login ok/denied, logout, key create/delete, key revoke/unrevoke, role
  change). Mutations take the acting identity as a required argument and the
  store is the single emit point, so both the HTTP and MCP surfaces are covered
  and no surface can act without an audit line. `audit=info` is forced in the
  default log filter so a bare `warn` fallback cannot swallow a successful key
  create.
- Log sink is selectable: human text by default, `LOG_FORMAT=json` emits one JSON
  object per line with fields flattened, `target` present, and the request span
  embedded, so audit records ship and index without parsing prose.
- A handler panic is caught at the innermost layer and returned as a 500, so a
  bug logs and counts as a server error instead of resetting the client
  connection.
- Logout is attributed: `logout_session` returns the session owner, so a real
  sign-out closes the lifecycle in the audit trail (best effort, since the
  client's logout always succeeds).
- Meta introspection is deny-by-default. `core::catalog::INTROSPECTABLE_TABLES`
  is the one allowlist: `fetch_table_names` lists only those names and
  `fetch_rows` answers 404 for anything else. This closed a credential hole, not
  just a naming one: `fetch_rows` ran `SELECT *` for any `ident`-valid name, so a
  `read:catalog` key (the default scope) could read `api_keys`,
  `dashboard_users`, and `sessions` (hashes), while the old
  `NOT LIKE 'sqlite_%'/'turso_%'` filter leaked the engine's
  `__turso_internal_mvcc_meta`. `questions`/`novel_questions` stay off the
  allowlist so the withheld answers stay withheld.
- Every `api/v1` read is key-gated: `novels::list` and `novels::detail` were the
  last two taking no `AuthedKey`.
- `is_busy` retries `conflict` as well as `busy`/`locked`, so a commit-time
  conflict retries instead of surfacing. The engine's Busy/BusySnapshot text is
  "database is busy"; a conflict is worded around "conflict", which the old
  matcher missed.

## Decisions worth keeping

- Observability is three separate things: metrics (numbers), logs (events), and
  audit (attributable security and business events). Audit is neither debug
  logging nor metrics; it is its own target so it can be filtered and shipped on
  its own.
- Audit records decisions and lifecycle, not data. Login, key lifecycle, and role
  changes are audited because their durable record is transient (sessions, a
  deleted key) or absent (no role history). Report filings are not audited: they
  persist an attributed row (key id plus timestamp) in their own table, so
  copying them into logs would be noise, not a trail. A privileged change that
  matched nothing is still logged, at WARN, so a probe is never silent.
- Admin-only endpoints live under `/api/internal/admin/*`; everything else under
  `/api/internal/*` is customer or session.
- Log format is a deployment concern, chosen by `LOG_FORMAT` beside `RUST_LOG`,
  not app config: it changes how output is rendered, never what the app does.
- The meta surface is deny-by-default: a table is visible only if it is named in
  `core::catalog::INTROSPECTABLE_TABLES`. A deny list fails open the moment a
  sensitive table is added; an allow list fails closed.
- No long poll. Pull on an interval and pool connections, so reads and writes
  never queue behind the sync engine's single IO worker.
- Reads fail fast (5s), writes get cloud headroom (30s), and a global 30s net
  covers any route that forgets its own budget.
- 16KiB request body cap, ~5x the largest body we accept.
- Production code has no `unwrap`/`expect`, no `#[allow]`, no `unsafe`.
