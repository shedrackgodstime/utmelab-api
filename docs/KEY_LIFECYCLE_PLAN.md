# API Key Lifecycle Plan — dashboard + `/internal/*` + Turso

> **Date:** 2026-10-11. **Status 2026-10-13: §§1–5, 7, 8, 11 LANDED via D53**
> (CLI issue/list/revoke/rotate/import, Turso-or-error runtime, 30s TTL,
> live-verified §11.1). **PARKED for Phase 2:** §3.2 accounts+sessions,
> §3.3 usage metering, §6 `/internal/*`, §9 phasing tail, §10 open
> questions. Nothing below changes code until promoted to
> `QUESTION_BANK_DECISIONS.md` (D-ID) + `TODO.md`.
> **Scope decision (2026-10-11): NO auth, NO accounts, NO web work now.** v1 `/api/*` must be ready and solid first. Keys are issued by CLI, tested by key alone, and the code is shaped so accounts/dashboard slot in later without a rewrite. Account-shaped fields exist in the model but stay defaulted/unused until Phase 2.
> **Goal:** define how an API key is born, used, and killed with CLI-only issuance — testable today with zero accounts — while keeping every seam accounts will need later.
> **Context:** today keys are CLI-issued into `var/api_keys.json` (`KeyStore::open_json`), held by value in `AppState`, resolved by `sha256` in `api/auth.rs:Caller`. `GET /api/v1/keys/me` is the probe. `src/api/internal/` is an empty stub (D33: unversioned, session-cookie, never in spec). `web/src/pages/dashboard/index.astro` is a static shell. Turso env exists (`.env`: `TURSO_DB_URL`, `TURSO_DB_TOKEN` rw, `TURSO_DB_TOKEN_READONLY`, `TURSO_API_KEY`) but the `turso = 0.8.2` dep is **unused** — no client code yet. Note the `TURSO_` prefix typo in `.env` vs the `TURSO_` the code/docs will expect — normalise to `TURSO_` and accept `TURSO_` as deprecated alias with a boot warning.

## 1. Actors (four, never confused)

| Actor | Authenticates with | Touches | Never touches |
|---|---|---|---|
| Anonymous browser | nothing | catalog (`/exams`, `/subjects`, `/syllabus`, `/novels`, `/passages`, `/health`, `/openapi.json`) | anything metered |
| API key (machine) | `x-api-key: sk_...` | `/api/v1/*` metered | `/internal/*` ever |
| CLI operator (us — the ONLY issuer in v1) | shell on the box | `key create/revoke/list`, testing via `keys/me`, recovery | nothing — issuance lives here until dashboard exists |
| Dashboard user (human — FUTURE, not now) | session cookie (design-only) | nothing yet; `/internal/*` stays empty stub | everything until Phase 2 |

Rule for v1: **CLI mints keys; keys never mint keys.** Sessions rule is parked with the dashboard, not deleted — the `account_id` column and `Session` extractor shape exist so Phase 2 is additive.

## 2. Lifecycle states

```text
created (plaintext shown ONCE by CLI, never again)
  -> active (resolves, spends rate budget, accrues usage)
  -> revoked (terminal, indistinguishable from unknown to callers)
  -> expired (optional `expires_at`; same wire behaviour as revoked)
suspended/rotate: designed now (columns + trait methods exist), built with dashboard — v1 ships create/active/revoked/expired only.
```

Wire behaviour for `revoked | expired | unknown` (and later `suspended`): identical `401 unauthorized`, no distinguishing field (keep today's `auth.rs` guarantee — prevents id enumeration). v1 owner visibility = CLI output; dashboard visibility comes Phase 2.

## 3. Data model (Turso is the owner; file is legacy)

### 3.1 `api_keys` — the row

```sql
CREATE TABLE api_keys (
  id            TEXT PRIMARY KEY,
  key_hash      TEXT NOT NULL UNIQUE,
  key_prefix    TEXT NOT NULL,
  label         TEXT NOT NULL,
  account_id    TEXT NOT NULL,
  plan          TEXT NOT NULL DEFAULT 'free',
  scopes        TEXT NOT NULL DEFAULT 'questions:read reports:write',
  rate_limit    INTEGER NOT NULL,
  quota_monthly INTEGER,
  created_at    TEXT NOT NULL,
  last_used_at  TEXT,
  expires_at    TEXT,
  suspended_at  TEXT,
  suspend_reason TEXT,
  revoked_at    TEXT
);
CREATE INDEX idx_api_keys_account ON api_keys(account_id);
```

`id` is `key_<32hex>` (stable, safe to log). `key_hash` is sha256 hex of `sk_...`; plaintext never stored. `key_prefix` is first 8 of plaintext for support lookup (never authenticates). `plan` gates verified/explanations later (R11). `rate_limit` is req/min (D26: column, not key type).

### 3.2 `accounts` + `sessions` (when dashboard lands; stub shape now)

```sql
CREATE TABLE accounts (
  id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL, plan TEXT NOT NULL DEFAULT 'free'
);
CREATE TABLE sessions (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
  session_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT
);
```

### 3.3 `api_usage_daily` (metering without blocking requests)

```sql
CREATE TABLE api_usage_daily (
  day TEXT NOT NULL, key_id TEXT NOT NULL, route TEXT NOT NULL,
  hits INTEGER NOT NULL DEFAULT 0, limited_429 INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, key_id, route)
);
```

Written by a background flusher (channel, batch every ~10s), never inline. Powers dashboard Usage + future billing.

## 4. How it flows (v1: CLI-only, no accounts)

### 4.1 Issue — `cargo run -- key create` is the ONLY issuer in v1
```bash
cargo run -- key create --label my-laptop --rate-limit 60
# prints sk_live_... ONCE + id/label/rate_limit; stores only sha256
cargo run -- key list            # NEW: id/prefix/label/rate_limit/status (no secrets)
cargo run -- key revoke --id key_abc
```
Test immediately, no account involved:
```bash
curl -H "X-API-Key: sk_live_..." localhost:8080/api/v1/keys/me
curl -H "X-API-Key: sk_live_..." "localhost:8080/api/v1/questions?per_page=1"
```
`account_id` defaults to `'local'` on every row; `plan` defaults `'free'`. Columns exist so Phase 2 is additive, but v1 code never branches on them.

### 4.2 Use (hot path — must stay fast, account-free)
`Caller::from_request_parts`: `x-api-key` -> sha256 -> lookup. Order in v1: **in-memory index (file-loaded) -> resolve**; with Turso later: **cache (TTL ~30s) -> Turso**. On hit, spend per-key token bucket, attach `Caller{key}`. On miss/revoked/expired -> identical `401`. No account lookup, no session, no join — the hot path must not know accounts exist.
Budget: p99 auth < 5ms cached, < 80ms uncached.

### 4.3 Manage — CLI in v1, dashboard shape parked
- v1: `key list` (safe columns only), `key revoke --id` (next request 401s — requires R1 fix: server must see file changes without restart), `key rotate --id` (successor + grace `expires_at`, new plaintext once). Suspend/unsuspend columns + trait methods exist but CLI need not expose them until abuse/billing exists.
- Phase 2 maps 1:1 to `/internal/*` (`POST /internal/keys`, `/revoke`, `/rotate`, `/suspend`) — same semantics, different transport (session cookie). No redesign.

### 4.4 No bootstrap problem — CLI IS the path
No migration, no recovery split: file works today, Turso later via `key import --from var/api_keys.json` (one-time, dry-run counts, refuses overwrite, prints skips — D51 honesty rule). CLI talks to Turso only; `KeyBackend::File` exists for tests and as the `key import` source, never a runtime fallback.

## 5. Code shape to build NOW (v1: no accounts, no sessions, no web)

Build the seam so accounts/dashboard are pure addition later:

- `ApiKey` gains `account_id (default 'local'), plan (default 'free'), scopes, quota_monthly, key_prefix, last_used_at, expires_at, suspended_at` (never plaintext, never hash). v1 never branches on `account_id/plan` — they ride along. New `KeyStatus {Active, Revoked, Expired (+ Suspended reserved)}` + `status()` + `is_live()`.
- New `KeyStore` trait: `resolve (live only) / create / list / revoke / rotate / record_use (best-effort)`. Suspend methods on the trait now (so Phase 2 needs no trait change) but no CLI flag until needed. Implementations: `JsonKeyStore` (existing file logic, extended fields) + `TursoKeyStore` (Phase 1) + `CachedKeyStore<T>` (TTL wrapper, Phase 1).
- `AppState` changes (all v1, no dashboard): `keys: Arc<dyn KeyStore>` (fixes R1 stale keys — revoke effective without restart), limiter/reports to `tokio::sync::Mutex` (fixes R3). NO `sessions` field yet — `/internal/*` stays an empty stub returning nothing; session extractor lands with Phase 2.
- `auth.rs::Caller` stays the only gate for `/api/v1/*`, unchanged semantics, zero account awareness.
- CORS: NO split in v1 — keep single `*` + no credentials for everything (dashboard doesn't exist to need same-origin + CSRF; split lands with Phase 2).
- Config now: `KEY_CACHE_TTL_SECS=30` (used Phase 1), `TURSO_DB_URL` / `TURSO_DB_TOKEN` recognised but optional (file when unset). `SESSION_*` NOT yet — no session code in v1. Accept `TURSO_*` alias with warn until `.env` fixed.

## 6. `/internal/*` — PARKED, contract sketched only

Stays an empty stub through v1 (D33 still holds: unversioned, never in spec). When Phase 2 lands, same semantics as the CLI with session-cookie transport:

```text
GET    /internal/me                -> {account, plan}
GET    /internal/keys              -> [{id, prefix, label, plan, rate_limit, status, last_used_at, created_at}]
POST   /internal/keys {label}      -> 201 {id, key: PLAINTEXT_ONCE, ...}
POST   /internal/keys/{id}/revoke  -> {id, status: revoked}
POST   /internal/keys/{id}/rotate  -> 201 {id: new, key: PLAINTEXT_ONCE, supersedes, grace_until}
GET    /internal/usage?days=30     -> [{day, key_id, route, hits, limited_429}]
```

Until then: NO session code, NO cookie, NO CSRF, NO `Session` extractor in v1. Public `GET /api/v1/keys/me` is the v1 probe AND the future dashboard "test your key" button — one route, two callers.

## 7. Security notes (v1-minimum; billing split deferred)

- Plaintext: `sk_live_` + 32 random bytes hex (keep current entropy); CLI prints once, never logged (logs carry `id`+`prefix` only).
- Storage: sha256-of-256bit-random is fine while keys are bearer-random (no guessing surface); reserve `hash_version` column for future argon2id. Never rehash on read.
- `key_prefix` lets us find a key from `sk_live_a1b2...` without the secret; prefix alone never authenticates.
- Revocation must be effective without restart (R1 fix — file-watch or reload-on-resolve for v1; cache-invalidate for Turso later).
- Sessions/cookies/CSRF: parked with Phase 2, not in v1.
- Rate limit per-key bucket in memory (D27). Monthly quota column exists, unenforced until billing.
- Turso tokens: rw token server-env only, never in `web/` build; readonly for probe/dev. `TURSO_` typo alias until `.env` fixed.

## 8. Migration file -> Turso (one command, reversible)

`cargo run -- key import --from var/api_keys.json` maps `{id, key_hash, label, rate_limit, created_at, revoked_at, account_id='local-cli', plan='free', key_prefix='unknown'}` (prefix backfilled on next rotate; old keys keep working). Dry-run counts first; refuses to overwrite live rows; prints every skip with reason (D51 honesty rule). Cutover: `CachedKeyStore(Turso)` primary, file read-only fallback; then file retired to `var/api_keys.json.bak` + CLI recovery only.

## 9. Phasing (API-first; web last)

- **Phase 0 — v1 seam (NOW, no dashboard, no Turso client, no sessions):** `KeyStore` trait, extended `ApiKey` (account fields defaulted), `key list` + `key rotate` CLI, `AppState.keys: Arc<dyn KeyStore>` (R1), `tokio::Mutex` (R3), `TURSO_` env normalisation. Testable with curl + key alone. Fixes R1 structurally.
- **Phase 1 — Turso for keys (still no accounts/web):** research documented `turso` client, `TursoKeyStore` + `CachedKeyStore`, `key import`, usage flusher. File becomes fallback. Hot path still account-free.
- **Phase 2 — accounts + dashboard (NOT now):** `accounts/sessions` tables, sign-in (mechanism TBD), `/internal/*` endpoints, static shell wired, CORS split + CSRF.
- **Phase 3 — metering/billing (with dashboard):** usage UI, quota enforcement, `plan` gating on verified/explanations (R11), suspend flows.

## 10. Open questions (Phase 2 parked; v1 question only)

- v1: free rate default (60/min today — keep?) + do we ship `key rotate` in v1 or revoke-only first? (recommend: ship rotate — cheap, avoids plaintext re-issue pain).
- Parked with dashboard: sign-in mechanism, one-account-many-keys?, free monthly quota.

## 11. Turso Rust SDK — what the docs say (2026-10-11)

Source: `https://docs.turso.tech/sdk/rust/quickstart.md` + `/connect/rust.md` + `/sdk/rust/reference.md`.

- Three crates: `turso` (local/embedded + `sync` push/pull, MVCC, no C compiler), `turso_serverless` (remote Turso DB over the wire — for servers), `libsql` (remote ONLY with `remote` feature for libSQL-engine DBs; `core`/`replication` need a C compiler — this is why D28 dropped it: ~30min phone builds for a service that never runs SQLite locally).
- Our `.env` holds a `turso://…` URL, i.e. a Turso-engine database → the matching remote crate is **`turso_serverless`**, not `libsql`. Docs env names are `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN`; ours are `TURSO_DB_URL` / `TURSO_DB_TOKEN` (+ `READONLY`) — map both, warn on mismatch.
- Install per docs is `cargo add turso_serverless tokio --features tokio/full` — note: that is exactly the stray `cargo add turso tokio --features tokio/full` process seen on this box (teammate following the quickstart). We keep our minimal tokio features and add only what the compiler demands; do NOT commit `tokio/full` blindly.
- API shape we will use (Phase 1): `turso_serverless::Builder::new_remote(url).with_auth_token(token).build().await?`, `db.connect()?`, `conn.execute(sql, params).await?` with `?`/`?1` positional or `:name` named bindings, `conn.query(sql, params).await?` → `rows.next().await?` → `row.get(i)?`, plus `prepare`, `transaction` (`tx.commit().await?`), `execute_batch` for DDL.
- **Decision for Phase 1 (keys): use `turso_serverless` (authoritative remote reads) + `CachedKeyStore` TTL ~30s, NOT local+sync.** Rationale: revocation must be globally visible on next request; `turso::sync` local-first would need CLI `push` + server `pull` choreography per revoke — extra moving parts for zero benefit at one instance. Serverless read-per-miss is fine behind the cache (p99 <5ms cached); usage writes batch async.

### 11.1 Verified live (2026-10-11)

Phase 1 shipped and smoke-tested end-to-end against the **real Turso database** (`TURSO_DB_URL`/`TURSO_DB_TOKEN` were exported in the dev shell, so `serve` auto-selected the remote backend):

1. `key create` (CLI process) → row + `api_keys` DDL landed in Turso.
2. `GET /api/v1/keys/me` with the new key → **200**, full D53 shape (`account_id=local, plan=free, key_prefix, scopes`).
3. `key revoke` (CLI, second process, server not restarted) → next probe **200** (server's cache still fresh — see caveat), probe after 35s → **401**. Cache TTL expiry confirmed.

**Caveat recorded, honest not hidden:** cross-process revoke (CLI today) is visible to a running server **within `KEY_CACHE_TTL_SECS` (default 30s)**, not instantly — a separate process cannot invalidate the server's in-memory cache. Same-process revokes (Phase 2 dashboard → `/internal/*` on the server itself) are immediate via cache invalidation. The file backend is unaffected (mtime reload = immediate). TTL is configurable for tighter windows.

> Next: promote Phase 0 to D-ID + TODO Now and build the trait + `Arc<dyn KeyStore>` + `key list/rotate` CLI. No sessions, no `/internal/*`, no web until v1 API is solid.
