# API Review — Code Findings & Hardening Plan

> **Date:** 2026-10-11. **Scope:** full `src/`, `tests/`, `tools/`, `config/`, `data/`, `web/` as built on `main@656711c`.
> **Status:** review record, not decisions. Nothing here changes behaviour until it is promoted into `QUESTION_BANK_DECISIONS.md` with a D-ID and into `TODO.md` as work.
> **Rule:** this file observes; `QUESTION_BANK_DECISIONS.md` decides; `TODO.md` schedules.

## 0. Verdict

Unusually disciplined small API. The decision log is not theatre — `D11/D15/D16/D21/D23/D25-D27/D31-D33/D38-D39/D42-D43/D48-D52` are enforced in code **and** tests. Honesty as a feature (withheld counts, `subjects_ready + complete:false`, `weight:0 = not-published`, `year+source` orthogonal, `claimed_paper` servable-but-unverified) is the strongest trait.

But this is a v1 optimised for **correctness and saleability of content**, not for **operations, scale, or evolution**. Content is the blocker to revenue (1362/1522 unverified); operations is the blocker to trust (key reload, limit visibility, caching, async locking).

Live counts at review time: `questions=1522, subjects=34, topics=566, subtopics=2092, passages=5, novels=6`. `claimed_paper=1362, imported=97, authored=63`. `verified true=160 / false=1362`. All `year=2025`. 17 paths in `web/openapi.json`.

## 1. What is genuinely excellent (keep)

1. **Boundary `bank | api | keys | reports` is real.** `src/bank/` has zero `axum`/`http`. `Store: Send+Sync` seam (`src/bank/store.rs`) is clean — `TursoStore` can arrive without moving a route. Six-way parity contract (types, id-order, paging totals, absence D16, fail-boot validation, `version()` D42) is stated in the trait docs.
2. **Fail-closed content loading.** `JsonStore::load() -> Result<_, StoreError>` collects *all* problems with file+id and refuses to boot (`src/bank/json.rs`, `src/main.rs:serve`). `tests/store.rs` proves it by corrupting scratch copies (dangling `subtopic_id`, answer-not-an-option-id, duplicate id).
3. **Withholding by default.** `bank/view.rs:render(q, include_explanation)` + `render_novel_question` + `tests/questions.rs:the_answer_is_withheld_by_default`. Right call.
4. **Spec-derived, tested contract.** `utoipa ToSchema` from handler return types; `tests/openapi.rs` calls every documented path; asserts paging defaults live in prose (utoipa cannot emit `default`); asserts `default` type matches schema type; `tests/cors.rs` does real preflight + `expose-headers: retry-after`.
5. **Operational minimalism that fits the stage.** Single binary (`serve|key|import|openapi`), static `web/dist`, Caddy split, one key type (D26), token-bucket/key O(1), sha256-only, `0600` + write-then-rename, 4s build after dropping `libsql` (D28).

## 2. P0 — real bugs / footguns (fix before new surface)

### R1. Keys go stale after boot — **RESOLVED 2026-10-11**
`KeyBackend` + reload-on-resolve (mtime) for file, cache invalidation for Turso. Verified live.

### R2. `render_novel_question` always returns `novel_id: ""` — **RESOLVED 2026-10-11**
`render_novel_question(novel_id, q, …)`; caller passes the novel id. Covered by shape parity tests.

### R3. `std::sync::Mutex` inside async handlers — **RESOLVED 2026-10-11**
Reports store now `tokio::sync::Mutex` (file IO happens under the lock). Limiter stays `std::Mutex` deliberately: pure arithmetic, never held across an await. Dead-bucket retention task wired (15-min interval against live-key list).

### R4. Paging edge `per_page=0` / `page=0` — **RESOLVED**
`questions_page` clamps `per_page.clamp(1, MAX_PER_PAGE)` and `page.max(1)` (`src/bank/json.rs:506-507`); `page_zero_is_treated_as_page_one` guards it.

### R5. `GET /topics/...` is N+1 over the bank
- **Where:** `src/api/v1/topics.rs:68-77` loops subtopics calling `questions_page(...,1,1)` per subtopic for `total_records`.
- **Bug:** fine at 1522 rows / small fan-out; wasteful and will hurt at 68k rows. Syllabus tree already carries counts.
- **Fix:** reuse `syllabus()` counts or add `Store::subtopic_counts()` batch; keep per-topic route as projection, not scanner.
- **Test:** count store calls per request (instrument or assert bounded time on 10x fixture).

## 3. P1 — API design gaps (decide, then build)

### R6. No rate-limit introspection — **RESOLVED 2026-10-11**
`X-RateLimit-Limit/Remaining/Reset` on every authenticated response (incl. 429), via `RateLimiter::peek()` (read-only) + `api/middleware.rs::response_headers`. Remaining includes the current request. Tests in `tests/headers.rs`.

### R7. Offset paging only — need cursor for sync
Today: `page/per_page` id-ordered, stable while bank immutable in RAM. `import` on live server or Turso inserts shift offsets.
Fix: keep offset for docs/browsers; add cursor (`?after_id&limit`, opaque, id-ordered) for `/questions` before selling sync. `bank_version` polling + cursor = sync protocol.

### R8. Search `?q=` is substring full-scan
Today: `to_lowercase().contains()` O(n) — fine at 1.5k, dead at 68k (D9 Turso rows). Noted push-down as `LIKE` loses ranking.
Fix: keep `q` as find-my-question helper, never promise relevance; decide relevance story (FTS5/trigram) only when bank justifies it. Document limits in `guides/finding-questions.md`.

### R9. No HTTP caching despite `bank_version` — **RESOLVED 2026-10-11**
`ETag: "<bank_version>-<uri8hash>"` + `If-None-Match → 304` (empty body, no token spent) on all `/api/v1` GETs except `/keys/me`; `Cache-Control: public, max-age=3600` catalog / `60` questions. Per-URI etag so a changed filter never 304s. Tests in `tests/headers.rs`.

### R10. Filtering asymmetry — `?subtopic=` alone is global
- `GET /subjects/{exam}/{slug}` requires exam (good D21), but `?subtopic=` without subject/exam is global. Subtopic slugs may collide across subjects.
- Fix options: require `subject` when `subtopic` present (400 `subtopic_needs_subject`), or guarantee globally-unique subtopic slugs and document. Former safer.

### R11. One key type will not survive pricing
- D26 right for now, but `verified` is the paywall and `include_explanation=true` is the field charged for — today any key can set it.
- Fix: add `ApiKey{plan: free|paid}` + gate in `render()`/`report()`; document free vs paid in guides. Do with billing/dashboard, not before (per TODO parked).

### R12. Report cap semantics mismatch
- Code `recent_count()` (sliding 24h?) vs error text "resets at midnight UTC". Pick one, implement, test boundary (23:59 → 00:01 UTC).
- Also wire `RateLimiter::retain()` — exists but never called; long-run leak one entry per key ever seen. Call on revoke + periodic.

## 4. P2 — ops / security / pipeline notes

### R13. Auth details
- `Unauthorized` for unknown|revoked|malformed is correct (no enumeration). `hash_key = sha256(presented)` + hashmap lookup — no timing-compare issue. Log key *id* server-side on 429/401, never hash/plaintext.
- `RateLimiter` in-memory `HashMap<key_id, Bucket>` — restart wipes budgets (generous), single-process only. Two replicas double-spend. Fine until >1 binary, then Turso/Redis.

### R14. Hardening — **MOSTLY RESOLVED 2026-10-11**
Shipped: SIGTERM graceful shutdown, 64 KiB body limit, 30s request timeout, dead-bucket retention. Still open: per-request `X-Request-Id` + tracing spans (add when dashboard/first integrator needs observability).

### R15. Harvester / importer pipeline
- Polite crawler (2s, single worker, UA) is good; missing: `robots.txt` check, exponential backoff on 429/5xx, checksum for mirrored images.
- Images are absolute source-CDN URLs (hotlink breakage + referrer leakage). Mirror diagrams to owned `public/` or object storage at import time; store content hash.
- `cargo test` timed out at 30s in this environment — every test loads full `data/` + copies 1.2M JSON to temp. Split `unit (no data)` vs `integration (real bank)`; consider `cargo nextest` and scratch-once fixtures.

### R16. Novel domain nits
- R2 (`novel_id: ""`) aside: `category` free-string (`english|literature`) — make enum + 400 on unknown; `year`/`featured` filters compose correctly; sort newest-first in handler duplicates store order — pick one owner.
- No `marks` on novel questions is correctly rejected (flat 1-mark); keep.

## 5. Suggested sequencing (promote to TODO as D-items)

1. **P0 fixes:** R1 hot-reload keys, R2 novel_id, R3 async mutex, R4 paging normalise, R5 topic counts batch.
2. **Operability:** R14 hardening + R12 cap semantics + `retain()` wiring.
3. **Integrability:** R6 limit headers, R9 ETag/304, R10 subtopic scoping.
4. **Evolution:** R7 cursor paging, R11 plan-gating with billing, R15 image mirroring.
5. **Then expand:** `POST /papers` assembly (gated — ~103 verified held, 180 needed), Turso keys-first, content-second, R8 FTS only when justified.

## 6. Code pointers (where each finding lives)

| Finding | Files |
|---|---|
| R1 stale keys | `src/main.rs:serve`, `src/lib.rs:AppState`, `src/api/auth.rs`, `src/keys/store.rs` |
| R2 novel_id | `src/bank/view.rs:79`, `src/api/v1/novels.rs:questions` |
| R3 mutex | `src/lib.rs:55,57`, `src/api/auth.rs:44-48`, `src/api/v1/reports.rs:87-91` |
| R4 paging | `src/bank/store.rs:84-86`, `src/bank/json.rs:questions_page`, `src/api/v1/novels.rs:157-161` |
| R5 N+1 | `src/api/v1/topics.rs:68-77`, `src/bank/json.rs:syllabus` |
| R6 limits | `src/api/limit.rs`, `src/error.rs:retry_after_secs`, `web/src/content/docs/guides/errors.md` |
| R7 cursor | `src/api/v1/questions.rs`, `src/bank/store.rs:QuestionFilter/QuestionPage` |
| R8 search | `src/bank/json.rs:questions_page` text filter, `web/src/content/docs/guides/finding-questions.md` |
| R9 caching | `src/lib.rs:health`, `src/bank/json.rs:version` |
| R10 filter | `src/api/v1/questions.rs:Filter`, `src/bank/json.rs` |
| R11 plan | `src/keys/mod.rs:ApiKey`, `src/bank/view.rs:render`, `docs/TODO.md` parked billing |
| R12 cap | `src/reports/store.rs:recent_count`, `src/api/v1/reports.rs:91-95` |
| R13-R16 | `src/api/*`, `src/main.rs:shutdown_signal`, `tools/harvest*.py`, `src/import.rs`, `src/bank/model.rs:Novel*` |

> Next step: pick R1–R5 to fix, or promote any R-item into `QUESTION_BANK_DECISIONS.md` (new D-ID) + `TODO.md` (Now list). This file stays as the evidence trail.
