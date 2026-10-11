# TODO — utmelab-api

> Last updated: 2026-10-10. Items move here from `QUESTION_BANK_DECISIONS.md`
> when they become work. Done items stay for the record; delete nothing.

## Now (build in this order)

- [ ] **Assemble a paper** (`POST /exams/{exam}/papers`) — **gated on content, not on code** (D41). Scheme + readiness are live. Assembly (shuffle, `?seed=`, answers withheld, score) waits until a subject can fill its full count: JAMB needs 180 verified rows, we hold 103.
- [ ] **Search** — substring over `text`, case-insensitive, no ranking. Primarily our authoring/dedupe tool; consumers get a search UI free.
- [ ] **`Retry-After` on every 429** — two lines. Our status code invokes a standard our response doesn't honour.
- [ ] **CORS `*`** (D39) — one header via tower-http. Unblocks browser-app consumers; no new risk past D26.
- [ ] **`bank_version` in `/health`** — content hash or timestamp. Cheap invalidation so consumers poll one tiny endpoint instead of the bank. (Replaces webhooks for now.)

## Content (English-first, D34)

- [ ] English bank: 155 questions → keep deepening thin subtopics (emphatic-stress ×2 is thinnest)
- [ ] Passages: 5 exist; comprehension needs a bench, not one passage per type
- [ ] `verified=true` backlog: 103/155 — a paying customer buys verified, currently a thin shelf
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

- [x] `GET /exams/{exam}/papers` — scheme + honest readiness (D41); 16 paths
- [x] Report endpoint `POST /questions/{id}/report` (D38): closed reasons, no PII, 10/day, dedupe, queue-not-action
- [x] Constant closed (D11): Question, Option, Explanation, 5 tables + notes deferred
- [x] Exam-scoped subjects (D21), answer-by-id (D15), `verified` (D17)
- [x] Key auth, per-key rate limits, RFC 9457 errors, derived OpenAPI (D25–D28, D31)
- [x] Syllabus surface with coverage + objectives (D19)
- [x] Novel domain with rotation + 50-minimum enforcement (D35, D36)
- [x] Static web tier, no JS runtime (D32); browser-reachable `/internal/*` (D33)
- [x] Pushed: `utmelab-api` @ `2c5b451`, `UTME-Lab` @ `6a1a016`
