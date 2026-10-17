# UTME Lab API: foundation notes

Working notes for hardening the serving foundation. One entry per known gap,
highest value first. Delete an entry when it is closed.

## Porting gaps (old/src -> src/), ordered

`utmelab-api-old/` is a source of capabilities, never of structure. We take
what it served and serve it our way: no `bank/` tree, no in-process bank
promotion, no hand-kept contract, no duplicate admin surface. Ordered most
important first, with standards, enforcement, and single sources of truth
before features. Delete an entry when it is closed.

### 1. `store/schema.rs` is not the single source of truth it claims  (standards)

`store/schema.rs` says it is "the single source of truth for production
shapes: table DDL plus a `contract_version` handshake". Its `DDL` holds five
tables (`meta`, `api_keys`, `dashboard_users`, `sessions`, `reports`), while
`store/catalog.rs` reads fourteen more that are declared nowhere: `questions`,
`verifications`, `subjects`, `topics`, `subtopics`, `topic_countries`,
`exam_requirements`, `passages`, `novels`, `novel_chapters`, `novel_characters`,
`novel_themes`, `novel_questions`, `blueprints`. A domain shape can move and
the contract guard will not notice, so the module's promise is false for the
tables that matter most.

How: declare the domain tables in `DDL` (idempotent `CREATE TABLE IF NOT
EXISTS`) at the columns `catalog.rs` reads, then bump `CONTRACT_VERSION`. One
decision to state in code: the pipeline is today's creator of those tables, so
declaring them makes the API a co-owner of the shape. Keep creation idempotent
and additive-only via `ensure_column`, and add a schema test asserting every
table `catalog.rs` reads is declared. This is the guard G1 leans on.

### 2. The MCP surface declares parity it does not enforce  (enforcement)

`mcp/mod.rs` says "tools wrap the same `core` functions the HTTP handlers
call, so parity is structural". It is not. `mcp/resources.rs` is a one-line
placeholder that the router does not even mount, and `mcp/tools.rs` exposes
three admin tools (`list_tables`, `revoke_key`, `unrevoke_key`) that duplicate
`meta/tables` and `/api/internal/admin/keys/revoke` under a second auth. A
declared but unenforced surface is the same smell that removed `write:catalog`.

How: decide and encode. Either build it (resource and tool handlers wrapping
the same `store` reads, keyed by `AuthedKey` and scoped like HTTP, with a test
asserting MCP and HTTP answers agree), or delete the unwired `resources`
module and correct the doc comment. No third state where the tree promises a
parity nothing checks.

### 3. Surface-level keyed tests are missing  (enforcement)

Only `api/v1/questions.rs` has a keyed handler test, the pattern added with
the page envelope. The other ten `api/v1` modules, `internal`, and `mcp` have
none, and `tests/` is empty. The identity-plus-scope-plus-envelope rule is
enforced by convention and one example; nothing fails when a new module skips
it.

How: repeat the same harness per surface (offline replica, raw seed, real
router through `routes::router`, `x-api-key` header): no key is 401, wrong
scope is 403, revoked is 401, a live key gets a typed envelope. Mechanical, not
a redesign. Fold each new route's test into this list as it lands.

### 4. The subject detail trio is the only missing public read  (feature)

Old served 18 `/api/v1` routes; new serves 18. The composition differs by
exactly three: `GET /api/v1/subjects/{exam}/{slug}`,
`GET /api/v1/subjects/{exam}/{slug}/syllabus`, and
`GET /api/v1/subjects/{exam}/{slug}/coverage`. Nothing else in old's public
surface is unserved. Cost differs: subject is trivial (`get_subject` exists),
coverage is easy (`subject_stats` exists), syllabus is real work because new's
`list_syllabus` returns only `{slug, name, subtopics}` while old's carried
per-node counts, objectives, and country labels.

How: wire shapes in `core/models.rs` (`Coverage`, `Syllabus`, `SyllabusNode`);
a pure `core::catalog::assemble_syllabus(tree, rows, topics)` that counts rows
per topic through the subtopic map; a richer store read only if the objectives
need one; three handlers in `api/v1/subjects.rs` with `AuthedKey` and
`requires(SCOPE_READ_CATALOG)` and 404 as `AppError::NotFound`. Tests: the
`core` assembly test plus a keyed handler test per route.

### 5. Deferred: CLI verbs and the OpenAPI contract  (out of scope for now)

Recorded so it stays visible, not scheduled. Old's clap CLI had `key
create/list/revoke/rotate`, `import` (json and Turso), `openapi --out`,
`quarantine`, `audit-db`, and `verify`; new has serve plus `seed-admin`, with
key lifecycle now on the session-authed `/api/internal/admin/keys*` surface.
Still without a home: `rotate` (grace-period successor), `import`,
`quarantine`, `verify` (a `verifications` writer the API does not have), and
`audit-db` (partly replaced by `meta/tables` and `meta/rows`). OpenAPI is a
regression rather than a gap: old derived the spec from the handlers with
`utoipa` and served it at `/openapi.json` because a hand-written spec "kept
producing" bugs; new has no annotations, no served route, and a hand-written
`site/openapi.json`, so the bug class old removed is back.

### Not gaps (do not port back)

- The bank write path. `store/catalog.rs` has no writes by design: the
  pipeline promotes bank data into Turso and the API serves a synced replica.
  Old's two in-process bank writers (the `import` question upsert, the `verify`
  row) are promotion and review work, not serving work. If the serving app
  ever owns human verification writes, that is a new capability with its own
  design, and `write:catalog` returns to the vocabulary at that moment.
- The JSON-file bank and its cache (`bank/json.rs`, `bank/cache.rs`). New
  reads the replica only.
- DB audit (`db/audit.rs`). New audits to logs (`obs.rs`).
- The question-only report route. New's report is target-agnostic.

## Backlog

1. `GET /api/v1/exams/{exam}/papers` costs ~142ms (release) in the per-row
   `verified` predicate. Optimize only if it matters at the expected rate.
2. Consider an adaptive pull interval (longer when the replica is idle) if one
   request per `SYNC_SECS` is judged too chatty.
3. Capacity pass: the gate itself is measured (flat throughput, see Decisions).
   Remaining is the load model: run an HTTP load test against `questions` and
   `papers` once a key exists, size `WORKER_THREADS` to the VPS vCPU count, and
   set `DB_MAX_CONCURRENT` to expected peak concurrent DB work.
4. Classify `turso::Error::Busy`/`BusySnapshot` as typed retryable errors before
   `upstream()` stringifies them, instead of text-matching in `is_busy`.
5. Surface `stats()` (pending-change count, WAL size, last push time) read-only
   on the admin status; do not call `checkpoint()` ourselves.
6. The store write path (`execute_write`/`execute_ddl`) pushes to Turso, so it
   cannot run against an offline replica: only reads and the pre-write guards are
   covered today. Add a mutation test against a real replica (or a stubbed push)
   to cover key create/delete/revoke, role change, and report filing end to end.

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
- Session cookies are secure by default (`DEFAULT_COOKIE_SECURE = true`). The old
  default was `false`, so a missing `COOKIE_SECURE` shipped a non-`Secure` admin
  cookie. Now an unset variable fails closed; only an explicit `=0` opts out for
  local http.
- Paged endpoints now share one envelope, `core::models::Page`, built with
  `Page::new`. `questions` and `novels` no longer each hand-roll the
  `total_pages` arithmetic, so a new paged endpoint copies a constructor, not a
  formula.
- The porting surface gained its first tests. A keyed handler test drives the
  real router over `/api/v1/questions` (no key 401, wrong scope 403, revoked 401,
  live key 200 with the page envelope, answer withheld by default). `store`
  accounts gained tests for the credential reads (`verify_key`,
  `verify_session`, `list_keys`) and the mutation validation guards.
- `POST /v1/report` returns a typed `core::models::ReportFiled` instead of an
  ad-hoc `serde_json::Value`, so the public surface has one response idiom.
- The scope vocabulary now equals what a route enforces: the unused
  `read:reports` and `write:catalog` are gone, and the admin key grant names only
  enforced scopes.
- The read/write budget split is now real on the public surface: `reports` (the
  only write under `/api/v1`) is merged outside the read-timeout group in
  `api::router`, so it runs on the write budget like `internal` and `mcp`.
- `question_where` emitted the `verified` predicate twice under a copy-paste bug
  (the query still worked, with a duplicate condition and param). It is emitted
  once now, with a test pinning one placeholder per bound value.

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
- `DB_MAX_CONCURRENT` is a shedding/latency dial, not a throughput dial. Measured
  flat ~1.1–1.4k ops/s at gates 4/8/16/32 on an offline replica: the engine's
  rate is the ceiling. A smaller gate only sheds more (gate=8 answered 75% of 32
  concurrent readers with 503 for the same throughput gate=16 got). Keep it equal
  to the connection pool and tune it to expected peak concurrency; never treat it
  as a performance knob.
- Security settings default to safe: `COOKIE_SECURE` defaults on and the meta
  allowlist denies by default, because a missing or typo'd variable must fail
  closed, never downgrade.
- No long poll. Pull on an interval and pool connections, so reads and writes
  never queue behind the sync engine's single IO worker.
- Reads fail fast (5s), writes get cloud headroom (30s), and a global 30s net
  covers any route that forgets its own budget.
- 16KiB request body cap, ~5x the largest body we accept.
- Production code has no `unwrap`/`expect`, no `#[allow]`, no `unsafe`.
- A scope constant is declared only when a route enforces it. A granted scope
  nothing checks is a capability a key appears to hold; the vocabulary stays
  equal to enforcement, and admin tier bypasses scope lists regardless.
- The read/write timeout split follows the verb, not the router: reads fail fast
  at 5s, writes take 30s of cloud headroom, so a write module sits outside the
  read-timeout layer wherever it lives.
- The write path cannot run offline (it pushes to Turso), so store tests seed
  through a raw connection and stop at the validation boundary; happy-path
  mutation coverage needs a live replica.
- One page envelope, one response idiom (typed `core::models`), one identity rule
  (`AuthedKey` plus `require(SCOPE_*)`, except an endpoint about the caller's own
  key). These are written at the top of `api/v1/mod.rs` so a new module follows
  the rule, not the last file it read.
