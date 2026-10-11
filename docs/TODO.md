# TODO — utmelab-api

> Last updated: 2026-10-11. Items move here from `QUESTION_BANK_DECISIONS.md`
> when they become work. Done items stay for the record; delete nothing.

## Now

- [ ] **78 English questions are unanswerable as served** — they say "the underlined word" and we do not store which word. Full analysis and options in [`UNDERLINE_PROBLEM.md`](UNDERLINE_PROBLEM.md); recommended fix is `emphasis: Option<String>` on `Question`. **No `verified: true` on any of the 78 until this lands.**
- [ ] **6 novel questions still in the English bank** (stems begin "This question is based on Kabir Alabi Garba's The Lekki Headmaster") — move to the novel document (D35).
- [x] ~~**Merged key work (D53) has a failing test**~~ — **resolved 2026-10-11**: the prefix is intended (support lookup, never authenticates); the test now asserts the full plaintext is absent and any `sk_`-prefixed string is ≤11 chars. Suite is 72/72 green.

- [ ] **39 Lekki Headmaster questions still staged** in `data/inbox/lekki-headmaster-candidates.json`. Of 77 harvested, 9 were not novel questions (returned to the bank), 15 had truncated stems carrying no question at all, 1 duplicated an existing question with a garbled name, and only 4 could be verified against our own chapter summaries — those 4 joined the novel document (50 -> 54). The rest stay staged: their keys are third-party and our summaries cannot check their detail, so adding them would raise the count without raising trust.
- [x] **v1 key seam (D53, Phase 0+1)** — shipped 2026-10-11: `KeyStore::{list,rotate,reload_if_changed}`, extended `ApiKey` (`account_id/plan/prefix/expires_at`, defaulted), `KeyBackend::{File,Remote}` (async, one shape), `TursoKeyStore` (`turso_serverless`, DDL auto-create, 30s TTL cache, cache invalidation on revoke/rotate), `key list/rotate/import` CLI, config accepts `TURSO_DB_URL`/`TURSO_DB_TOKEN` (+alias warnings, half-creds fall back to file with warning). Verdict met: `cargo build` green, `cargo test` 72/72, clippy clean, live smoke vs **real Turso**: create→`/keys/me` 200→CLI revoke (no restart)→200 within TTL→**401 after TTL**. Known trade-off: cross-process CLI revoke visible within `KEY_CACHE_TTL_SECS` (30s), same-process revokes immediate — plan §11.1. File backend unchanged and still the dev default.
- [ ] **Assemble a paper** (`POST /exams/{exam}/papers`) — **gated on content, not on code** (D41). Scheme + readiness are live. Assembly (shuffle, `?seed=`, answers withheld, score) waits until a subject can fill its full count: JAMB needs 180 verified rows, we hold 103.

## Content (English-first, D34)

- [ ] **Grow the catalog (D50).** Government is in: 32 topics / 101 subtopics. Every remaining subject is one command: `python3 tools/import_syllabus.py --subject economics --display Economics`. Do Economics, Commerce, CRS, History, Geography next — then harvest.
- [ ] **Harvest 2025 UTME questions (D49).** `tools/harvest.py` works; the catalog blocker is now clearing. `claimed_paper` rows land unverified and unexplained, by design.
- [x] **A merge step** — `cargo run -- import [--dry-run]`, three gates, every refusal counted (D51). 675 rows in; 3 duplicates and 1 figure-less row refused.
- [ ] **Review the 675 `claimed_paper` rows into `verified`.** They are servable now and honest about origin. Verification is the paid tier, and it is the only thing standing between this bank and being sellable.
- [x] **Provenance follow-through (D47).** `source` and nullable `year` ship, but the 97 ported rows still carry an inherited `year: 2025` that was never checked against the paper they came from. Verifying or clearing those is the honest completion.

- [ ] English bank: 155 questions → keep deepening thin subtopics (emphatic-stress ×2 is thinnest)
- [ ] Passages: 5 exist; comprehension needs a bench, not one passage per type
- [x] **`verified` is 154/155.** 133 rows read line by line, 6 fixed. The only row left is `q_unassigned_civic_001`, which is withheld from serving anyway (D21). 133 rows were read line by line; 6 were fixed. The 7 still unverified are honest leftovers: 6 `fiction` comprehension questions that need their passage read against the stem, and `q_unassigned_civic_001`, which is withheld anyway (D21).
- [ ] **Re-check `word-stress` and `emphatic-stress` before trusting either pool.** They carried the only wrong answers in the audit — spot-check any new stress question twice.
- [x] **Option counts are correct** (D46): JAMB is 4 options @ 2.5 marks, verified against real papers. Five only in pre-CBT-era papers (1978). No work needed.
- [ ] **2-option question** `q_jamb_2025_math_coordinate_001` — a two-way choice in a four-way bank (the only one)
- [ ] Port 2025 English remainder by hand (101 non-novel done; 296 novel rows parked — stale, not ours)
- [ ] Novel `lekki-headmaster`: complete (12 ch, 35 chars, 50 Qs). Others are stubs.

## Parked (do not build — reason recorded)

- [ ] **Bulk export** — it's a pricing tier, not a feature. Tiers are parked with billing.
- [ ] **Webhooks** — no receivers exist. `bank_version` covers 80%.
- [ ] **Flashcard format** — presentation logic; `key_point`/`body` already serve it.
- [ ] **Sandbox** — the public catalog already is one.
- [ ] **Aggregate endpoint** — docs snippet instead; consumers need it client-side.
- [ ] **Changelog endpoint** — docs page instead.
- [ ] **Turso migration** — seam ready (`dyn Store`), trigger is volume + billing need, not curiosity.
- [ ] **Turso for keys** — file works for one key; research the documented client before touching it.
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
- [x] Pushed: `utmelab-api` @ `2c5b451`, `UTME-Lab` @ `6a1a016`
