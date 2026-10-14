# TODO — utmelab-api

> Last updated: 2026-10-14. Items move here from `QUESTION_BANK_DECISIONS.md`
> when they become work. Done items stay for the record; delete nothing. The
> full plan lives in [`ROADMAP.md`](ROADMAP.md) (P0 done, P1 done).

## Now

- [x] ~~**78 English questions were unanswerable as served**~~ — **backfilled 2026-10-13**: all 78 carry `Underline` marks (worksheet → read → apply; each target verified single-occurrence in its stem). Quarantine `underline_missing`: 78 → 0. Rows are answerable; `verified` still needs a human pass each (D62) — that is review work now, not backfill. Recorded limits: sound items mark whole words (letter-level died in the harvest); `t76545` has a suspect key (`bought`→*son*; mark stands, answer needs review).
- [x] ~~**6 novel questions still in the English bank**~~ — **resolved 2026-10-11**: the subject-scoped D35 guard (whole-word, case-sensitive, English/Literature only) caught **45** misfiled Lekki Headmaster questions. 41 moved into the novel document verbatim (original ids, `verified:false`), 4 exact duplicates dropped from the bank. Bank 2,416 → 2,371; novel doc 54 → 95.
- [x] ~~**Merged key work (D53) has a failing test**~~ — **resolved 2026-10-11**: the prefix is intended (support lookup, never authenticates); the test now asserts the full plaintext is absent and any `sk_`-prefixed string is ≤11 chars. Suite is 116 green (2026-10-14).

- [ ] **39 Lekki Headmaster questions still staged** in `data/inbox/lekki-headmaster-candidates.json`. Of 77 harvested, 9 were not novel questions (returned to the bank), 15 had truncated stems carrying no question at all, 1 duplicated an existing question with a garbled name, and only 4 could be verified against our own chapter summaries — those 4 joined the novel document (50 -> 54). The rest stay staged: their keys are third-party and our summaries cannot check their detail, so adding them would raise the count without raising trust.
- [x] **v1 key seam (D53, Phase 0+1)** — shipped 2026-10-11 (note: the trailing "file backend still the dev default" was retired by D53-final — runtime is Turso-or-error; file is tests + import-source only). `KeyStore::{list,rotate,reload_if_changed}`, extended `ApiKey` (`account_id/plan/prefix/expires_at`, defaulted), `KeyBackend::{File,Remote}` (async, one shape), `TursoKeyStore` (`turso_serverless`, DDL auto-create, 30s TTL cache, cache invalidation on revoke/rotate), `key list/rotate/import` CLI, config accepts `TURSO_DB_URL`/`TURSO_DB_TOKEN` (+alias warnings, half-creds fall back to file with warning). Verdict met: `cargo build` green, `cargo test` 72/72, clippy clean, live smoke vs **real Turso**: create→`/keys/me` 200→CLI revoke (no restart)→200 within TTL→**401 after TTL**. Known trade-off: cross-process CLI revoke visible within `KEY_CACHE_TTL_SECS` (30s), same-process revokes immediate — plan §11.1.
- [ ] **Assemble a paper** (`POST /exams/{exam}/papers`) — **gated on content, not on code** (D41). Scheme + readiness are live. Assembly (shuffle, `?seed=`, answers withheld, score) waits until a subject can fill its full count: JAMB needs 180 verified rows, we hold 163 (english, 2026-10-14).
- [ ] **`Cache-Control: public` on metered `/questions`** — flagged by the Jamb-Lab consumer notes (`docs/JAMB_LAB_NOTES.md` §3): a shared cache could serve paid-tier rows to URL-holders with no key. `private` may match the D27 metering intent. Review the middleware, decide, record.

## Content (English-first, D34)

- [ ] **Grow the catalog (D50).** Catalog stands at 582 topics across 25 JAMB subjects (2026-10-14). Remaining: subtopic coverage where thin, then questions — not more subjects.
- [ ] **Harvest 2025 UTME questions (D49).** `tools/harvest.py` works; the catalog blocker is now clearing. `claimed_paper` rows land unverified and unexplained, by design.
- [x] **A merge step** — `cargo run -- import [--dry-run]`, three gates, every refusal counted (D51). 675 rows in; 3 duplicates and 1 figure-less row refused.
- [x] ~~**Review the `claimed_paper` backlog into `verified`.**~~ — **done bank-wide 2026-10-14**: all 25 JAMB subjects reviewed end to end (17 batches + maths groundwork), 26 key fixes, documented parks only. Bank 2,186/2,247 verified (HANDOFF §7 items 18–37).
- [x] **Provenance follow-through (D47).** `source` and nullable `year` ship, but the 97 ported rows still carry an inherited `year: 2025` that was never checked against the paper they came from. Verifying or clearing those is the honest completion.

- [ ] English bank: 168 questions (163 verified) → keep deepening thin subtopics (emphatic-stress ×2 is thinnest)
- [ ] Passages: 6 exist; comprehension needs a bench, not one passage per type
- [x] ~~**`verified` is 154/155.**~~ — **superseded 2026-10-14 by bank-wide review**: 2,186/2,247 verified across all 25 subjects (was: 133 rows read line by line, 6 fixed; the English-only framing no longer describes the bank).
- [ ] **Re-check `word-stress` and `emphatic-stress` before trusting either pool.** They carried the only wrong answers in the audit — spot-check any new stress question twice.
- [x] **Option counts are correct** (D46): JAMB is 4 options @ 2.5 marks, verified against real papers. Five only in pre-CBT-era papers (1978). No work needed.
- [ ] **2-option question** `q_authored_math_coordinate_001` — a two-way choice in a four-way bank (the only one)
- [ ] Port 2025 English remainder by hand; 296 novel rows parked — not ours, not ported.
- [ ] Novel `lekki-headmaster`: complete (12 ch, 35 chars, 220 Qs). Others are stubs.

## Parked (do not build — reason recorded)

- [ ] **Bulk export** — it's a pricing tier, not a feature. Tiers are parked with billing.
- [ ] **Webhooks** — no receivers exist. `bank_version` covers 80%.
- [ ] **Flashcard format** — presentation logic; `key_point`/`body` already serve it.
- [ ] **Sandbox** — the public catalog already is one.
- [ ] **Aggregate endpoint** — docs snippet instead; consumers need it client-side.
- [ ] **Changelog endpoint** — docs page instead.
- [x] ~~**Turso migration (content)**~~ — **done 2026-10-14**: all 4 phases seeded with parity proofs + TursoStore read path + Turso-only serving (disk cache, hot reload). Schema was pinned (D64, `docs/DB_SCHEMA.md`); seam held (`dyn Store`). Clearing order completed: verifications (2,259) → questions (2,246) → passages + novels → catalog + blueprints, then read path, then cutover.
- [ ] **Billing/accounts** — with the dashboard, not before.
- [ ] **`/internal/*` routes** — stub exists; first endpoint lands when the dashboard needs it.
- [ ] **D10** — normalize the JSON's 5 subject names to JAMB's. Decided, trigger not pulled.
- [ ] **Study notes (D18)** — shape recorded, explicitly not v1.

## Done

- [x] Content audit: 2 wrong answers fixed, 1 missing explanation written, 1 duplicate stem retargeted (D45)
- [x] `GET /questions/{id}` — resolve a stored id; same shape and withholding rule as a list item
- [x] CORS `*` (D39) — preflight answered, `x-api-key` permitted, `Retry-After` exposed to JS
- [x] `?q=` search on `/questions` — substring, unranked, through the store seam (D44)
- [x] `Retry-After` on every 429, and only on 429s (D43)
- [x] `bank_version` in `/health` — content hash, not deployment hash (D42)
- [x] `GET /exams/{exam}/papers` — scheme + honest readiness (D41); 16 paths
- [x] Report endpoint `POST /questions/{id}/report` (D38): closed reasons, no PII, 10/day, dedupe, queue-not-action
- [x] Constant closed (D11): Question, Option, Explanation, 5 tables + notes deferred
- [x] Exam-scoped subjects (D21), answer-by-id (D15), `verified` (D17)
- [x] Key auth, per-key rate limits, RFC 9457 errors, derived OpenAPI (D25–D28, D31)
- [x] Syllabus surface with coverage + objectives (D19)
- [x] Novel domain with rotation + 50-minimum enforcement (D35, D36)
- [x] Static web tier, no JS runtime (D32); browser-reachable `/internal/*` (D33)
- [x] Keys on Turso (was: "Turso for keys" parked) — shipped D53: Turso-or-error at runtime, file tests + import-source only
- [x] Pushed: `utmelab-api` @ `2c5b451`, `UTME-Lab` @ `6a1a016`
