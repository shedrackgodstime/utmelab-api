# UTME Lab API: foundation notes

Working notes for hardening the serving foundation. One entry per known gap,
highest value first. Delete an entry when it is closed.

## Porting gaps (old/src -> src/), ordered

`utmelab-api-old/` is a source of capabilities, never of structure. We take
what it served and serve it our way: no `bank/` tree, no in-process bank
promotion, no hand-kept contract, no duplicate admin surface. Ordered most
important first, with standards, enforcement, and single sources of truth
before features. Delete an entry when it is closed.

### 1. Deferred: CLI verbs and the OpenAPI contract  (out of scope for now)

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
4. Surface `stats()` (pending-change count, WAL size, last push time) read-only
   on the admin status; do not call `checkpoint()` ourselves.
5. The store write path (`execute_write`/`execute_ddl`) pushes to Turso, so it
   cannot run against an offline replica: only reads and the pre-write guards are
   covered today. Add a mutation test against a real replica (or a stubbed push)
   to cover key create/delete/revoke, role change, and report filing end to end.

## Done

- Every catalog module now has a happy-path handler test through the real
  router, each on a seeded offline replica: `exams` (typed booleans/ints/rules),
  `blueprints` (measured columns and the honest empty list), `meta` (the
  deny-by-default allowlist on both list and row dump), `passages`, `topics`,
  `novels` (list, detail, quiz page), and `papers` (readiness carries the scope
  and requirements it judged). These prove the store read is wired, not the
  shape — the return types already do that.
- Contention is classified from the typed engine error, not from wording. The
  `upstream` conversion, the one place a `turso::Error` is still in hand, now
  maps `Busy`/`BusySnapshot` to `AppError::DbContended` (503, code `contended`),
  and matches the plain-message form the sync engine and the remote use (`busy`,
  `locked`, `conflict`) only on a `turso::Error::Error` — a serde or IO error is
  never retried however it reads. `is_busy` is now a typed read of that decision,
  so a reworded engine message can no longer silently stop retries.
- MCP now mirrors the keyed HTTP surface by construction. A read is a resource
  (`GET /mcp/resources/<tail>`, the `/api/v1` path without the version); an
  action is a tool (`POST /mcp/tools/*`), which is the MCP split falling out of
  the HTTP verb. Every route but the two admin tools mounts the *same handler*
  its HTTP twin does, so scope, gate, and rendered shape are written once and
  cannot drift; `tools::list_tables` was deleted as a duplicate of `meta::tables`.
  A parity test compares both outputs, and the sweep derives each resource twin
  from the HTTP read list, so a read added without its resource fails the sweep.
  This is not a JSON-RPC MCP server: the transport is plain keyed HTTP.
- Identity is structural, not per handler. `auth::api_key::verify_key` is a
  layer over each keyed router (`api/v1` reads and writes, `mcp`): it verifies
  the key once, applies the per-key limit, and stashes `Auth` in the request
  extensions; `AuthedKey` reads it back and rejects when it is absent. A route
  on a keyed router is now gated whether or not its handler asks for identity,
  so forgetting the extractor can no longer open one, and a keyed handler
  mounted off a keyed router fails closed (401) rather than trusting an empty
  extensions map. The layer sits inside each group's timeout, so verification is
  bounded like the work it guards, and outside CORS, so a preflight needs no key.
  Scope stays one `require` per handler because it differs per route. The sweep
  still proves the composition end to end, and its live-key 200s are what catch a
  layer that stops running. Unmatched paths under `/api` never reach the layer,
  so they keep answering 404.
- One response idiom now holds across the whole service. The dashboard, admin,
  and mcp surfaces answered `{"ok": ...}` and `{"key": ...}` through eleven ad-hoc
  `serde_json::json!` values; they now return `core::models::admin::{Applied,
  NewKey, SignedIn}`, so the typed-response rule stated for `api/v1` is the rule
  everywhere and no module spells a JSON object by hand. The revoke/unrevoke pair
  on both surfaces was the same handler twice; each now delegates to one private
  body that differs only by the flag.
- The store's column decoders are one rule, not six. `opt_u8`/`opt_u16`/`opt_u32`
  and `req_u8`/`req_u16`/`req_u32` were the same match over one integer variant,
  with per-caller error text ("exam count column…", "column out of u16 range…")
  and an unchecked `as` cast for `u32`; they are now `opt_int::<T>`/`req_int::<T>`
  over `TryFrom<i64>`, which names the column and range-checks every width. The
  strict 0/1 bool check inlined in `map_novel` and `map_subject` now calls
  `req_bool`, the one copy, so a `featured` or `is_compulsory` column that is
  neither fails the same way `verified` does.
- The default page size lives in one place. `page_query(Option, Option)` applies
  the 1/50 defaults before `page_bounds` clamps, so `questions` and `novels` no
  longer each write `unwrap_or(1)`/`unwrap_or(50)`.
- Test scaffolding has one home. `src/testing.rs` (`cfg(test)`) defines the
  offline replica, the schema seeding, the key minter, the `AppState` assembly,
  and the one HTTP call. Before this, six fixtures each rebuilt the replica, four
  re-typed the API-owned DDL, two re-declared the bank DDL, three re-hashed a key,
  and four hand-rolled the `AppState` literal; a shape change meant editing every
  copy. Now `api_schema` seeds the API-owned tables from `store::schema::DDL`,
  `bank_schema` the pipeline tables from one `BANK_DDL`, and `issue_key` hashes
  through `accounts::hash_key`, so a fixture declares only the rows it is about.
- The auth contract is enforced from one place. `routes` carries the route
  inventory and sweeps it through the real router: every keyed route refuses no
  key and a revoked key with 401, every session route refuses no cookie, and
  scope mismatch is proven with a read key on a read route, the write route, and
  an mcp admin tool. The sweep derives each MCP resource twin from the HTTP read
  list, so the mirror is asserted; identity itself is structural (see the gate
  entry below), so the sweep proves the composition, not each route by hand.
- The public surface is now a superset of old's. The last three routes are
  wired: `GET /api/v1/subjects/{exam}/{slug}`, `.../syllabus`, and
  `.../coverage`. The syllabus is assembled in `core::catalog::assemble_syllabus`
  (pure): the store's tree read gained order, weight, objectives, and country
  scope, and the core adds the counts old served, attributing each row to its
  subtopic and dropping topics scoped to another country. Coverage is the same
  counts without the tree. Both get a keyed handler test.
- `core/models.rs` is split by role into `core/models/{domain,wire,admin}.rs`,
  re-exported from `mod.rs` so every `core::models::…` path is unchanged. The
  domain shapes (the Rust half of `READ_SHAPES`) no longer sit beside the ops
  DTOs and the `Rendered*` wire forms, so a new type has an obvious home and the
  file cannot grow into the grab-bag we are porting away from.
- `store/schema.rs` is now the source of truth for the shapes the API reads.
  `READ_SHAPES` declares every table the store touches and the columns it
  depends on, and `check_shapes` (folded into `check_contract`, replacing
  `check_version`) fails the contract closed when one is missing, on boot and on
  every re-check. The bank tables are declared as reads, not `DDL`: the pipeline
  still owns and creates them, so a fresh replica cannot be given a loose shape
  that blocks the pipeline's. Two static tests assert every `DDL` table and every
  `INTROSPECTABLE_TABLES` entry has a declared shape.
- Admin-only endpoints now live under `/api/internal/admin/*` by convention, and
  `/health` stays the public liveness probe. The operational status moved to
  `/api/internal/admin/status`; the old customer path answers 404.
- Per-key rate limiting on `api` + `mcp`, enforced in the `verify_key` layer so
  no route can forget it (`RATE_LIMIT_PER_MIN`, admin unlimited by default). A
  key past its ceiling gets 429 with `Retry-After: 60`.
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
  (verify once in the `verify_key` layer, then `require(SCOPE_*)` per handler
  except an endpoint about the caller's own key; identity is a property of the
  surface, scope of the route). These are written at the top of `api/v1/mod.rs`
  so a new module follows the rule, not the last file it read. The response idiom
  is service-wide, not `api/v1`-only: the dashboard, admin, and mcp surfaces
  answer the same typed `core::models::admin` shapes, never a hand-built `json!`
  object.
- A column decoder is one rule per value class, not per column. `opt_int`/`req_int`
  over `TryFrom<i64>` name the column in the error and range-check the width, so a
  new integer column adds a call, not a helper; `req_bool` is the one strict 0/1
  check, so a nullable bool (`opt_bool`, nonzero) and a non-null one read
  differently on purpose rather than by whoever wrote each mapper.
- Test the boundary once, not the same assertion per route. Identity is one
  extractor and one `require`, so it is swept once over the whole route inventory
  (`routes`) instead of copied into every module; a typed response is the
  compiler's to check, so a per-module test is worth it only where it proves the
  store read is wired (questions, subjects, reports), not merely the shape.
- Test fixtures have one home, like the schemas they seed. `src/testing.rs` owns
  the offline replica, the API-owned `DDL`, the bank `BANK_DDL`, key minting,
  `AppState` assembly, and the request call; a test owns only its rows. A copied
  fixture is not just noise: a re-typed `api_keys` or bank shape drifts from
  production silently — the exact bug class `READ_SHAPES` catches — reintroduced
  in the tests meant to catch it.
- Shape declarations follow ownership. Tables the API creates go in `DDL`; tables
  the pipeline creates are declared in `READ_SHAPES` and validated, never
  created, because `CREATE TABLE IF NOT EXISTS` from the API would win a fresh
  replica and freeze a loose shape before the pipeline's promotion lands.
- Models split by role, not by consumer: `domain` mirrors the bank and pairs with
  `store::schema::READ_SHAPES`, `wire` is what we answer, `admin` is service and
  key state. One module keeps the store and the API agreeing on one shape; the
  submodules keep the layers visible.
- The served syllabus drops old's `note_available`, which was always `false`
  ("shape-only until D18 is activated"). A field that can only ever say one thing
  is noise a consumer will branch on; it returns with real meaning when notes
  exist.
