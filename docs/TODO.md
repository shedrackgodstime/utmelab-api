# TODO — utmelab-api

> Last updated: 2026-10-14. Items move here from `QUESTION_BANK_DECISIONS.md`
> when they become work. Done items stay for the record; delete nothing. The
> full plan lives in [`ROADMAP.md`](ROADMAP.md) (P0 done, P1 done).

## Pre-release checklist (first launch, audited 2026-10-14)

Everything between here and the first tag, in the order it should be done. Each
item names the gate that proves it, so "done" is a measurement and not a feeling.

### A. Content that is still missing

1. **64 rows have no subtopic**, so they serve but sit in no drill path. Physics
   (105) and the english/art/french/geography/computer-studies batch (28) are
   done; what is left is **history 24**, use-of-english 6 (deliberate, see
   below), hausa 4, igbo 4, and 1-3 each in thirteen subjects.
   *Gate:* every assignment reviewed against its question; `unattributed = 0`
   on the readiness endpoint.
1b. **History needs a world-history catalog.** 24 of its 79 rows are world
   history and the catalog holds none: jambsyllabus.com — the source we import
   from — parses 43 history topics, all Nigeria/Africa, and they are exactly
   the ones we carry. Versailles, Bretton Woods, NATO, the Cold War, the French
   Revolution have nowhere to live. The fix is the official JAMB brochure's
   world-history section, imported like every other subject.
   *Gate:* those 24 rows tagged; not a hand-written syllabus (D16/D50).
1c. **English has no "comprehension" subtopic** — only `fiction` and `cloze`.
   Five passage questions that carry no passage stay null rather than being
   filed under "fiction". *Gate:* a comprehension subtopic exists in the
   syllabus source, or the rows are dropped.
2. **61 rows are unverified** (not `pass`): use-of-english 5, french 5,
   music 5, geography 4, computer-studies 4, hausa 4, physics 3,
   agricultural-science 3, CRS 3, history 3, igbo 3, literature 2, and the
   tail. *Gate:* `python3 tools/review.py stats` — every row either passes or
   carries a documented park reason.
3. **13 rows sit in quarantine** (history 3, mathematics 2, use-of-english 2,
   physics 1, geography 1, hausa 1, igbo 1, CRS 1, physical-education 1).
   Each is either fixed or dropped — a quarantined row is neither content nor
   a decision. *Gate:* quarantine count 0, or a row-per-row reason list.
4. **Music's 5 parked rows need a music teacher** (76294, 76300, 76303,
   76320 figures; 76313 unanswerable as served). Their figures are attached and
   the readings are recorded — this is a human job, not a code job.

### B. Truth we are still carrying

5. **Two subjects have no headroom.** Yoruba sits at exactly 40/40 verified
   against a 40-question paper, music at 42/47. Any park, any quarantine, one
   bad key fix, and that subject's paper gate closes. *Gate:* deliberate —
   either build margin into those two, or record the zero-slack position as
   the reason a regression there is expected, not surprising.
6. **Seven D-rows are still PROPOSED** (D53, D67, D68, D69, D70, D71, D72).
   D68-D72 are load-bearing for everything shipped today. *Gate:* each
   accepted or rejected by a person, with the status flipped in the table.
7. **One cohort.** The bank is 2025 only, so every paper is served by the count
   gate and `blueprint` mode is dormant (D71). That is honest and intended;
   the consumer-facing copy must not claim balanced papers.

### C. Product decisions the release forces

8. **Paper endpoints are unauthenticated.** `/api/v1/papers/...` and
   `/blueprints/...` take no `Caller`, while `/questions` is key-metered — so
   the sellable payload is reachable without a key. *Gate:* a decision (meter
   the papers, or record them as public catalogue output) and, if metered, a
   test that an unkeyed call 401s.
9. **`Cache-Control: public` on metered `/questions`** — flagged by the
   Jamb-Lab consumer notes; `private` is probably the right answer under D27.
   *Gate:* a test pinning the header, so it cannot drift back.
10. **Blueprint coverage story.** Literature measures 34 of 40 seats,
    use-of-english states ranges, six subjects are section-level, fifteen are
    unmapped. Launch ships them all on the count gate; each needs blueprint
    rows to flip to the premium path. *Gate:* per-subject `governed` visible
    on the endpoint (done, D70/D71) and the launch copy says which mode each
    subject is in.

### D. Ops and release

11. **Turso is the source of truth for the binary and has no backup job.**
    Files can re-seed the content tables, so recovery is real but manual; the
    verification log and key store have no export at all. *Gate:* a runnable
    export (questions, verifications, keys) and a restore rehearsed once.
12. **Deploy secrets** (`VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_KEY`,
    `VPS_KNOWN_HOSTS`) must exist on this repo, and the first real release is
    a tag, not a workflow dispatch. *Gate:* a `v0.1.0` deploy that serves
    `/health` from the VPS.
13. **Rate limits and daily caps** are set to dev defaults (60/min). Launch
    values are a pricing decision (O5 is still open). *Gate:* values chosen
    and pinned in config, not left to the environment.
14. **An uptime check on `/health`** — it reports bank version, subjects,
    questions and withheld count, so it is the one signal worth watching, and
    nothing watches it yet.
15. **Consumer docs** (`site/`, README) must state the launch position:
    25/25 JAMB subjects serve a full-length paper, answers withheld, mode
    disclosed, per-subject year 2025.

### E. Standing (not launch blockers)

16. Harvest for 2025 is exhausted; more content means older cohorts or
    authoring, and older cohorts re-activate `blueprint` mode by themselves.
17. Duplicate audit runs on every content change (`tools/dup_audit.py
    --strict`, `tests/dedup.rs`).

## Now

- [x] ~~**78 English questions were unanswerable as served**~~ — **backfilled 2026-10-13**: all 78 carry `Underline` marks (worksheet → read → apply; each target verified single-occurrence in its stem). Quarantine `underline_missing`: 78 → 0. Rows are answerable; `verified` still needs a human pass each (D62) — that is review work now, not backfill. Recorded limits: sound items mark whole words (letter-level died in the harvest); `t76545` has a suspect key (`bought`→*son*; mark stands, answer needs review).
- [x] ~~**6 novel questions still in the English bank**~~ — **resolved 2026-10-11**: the subject-scoped D35 guard (whole-word, case-sensitive, English/Literature only) caught **45** misfiled Lekki Headmaster questions. 41 moved into the novel document verbatim (original ids, `verified:false`), 4 exact duplicates dropped from the bank. Bank 2,416 → 2,371; novel doc 54 → 95.
- [x] ~~**Merged key work (D53) has a failing test**~~ — **resolved 2026-10-11**: the prefix is intended (support lookup, never authenticates); the test now asserts the full plaintext is absent and any `sk_`-prefixed string is ≤11 chars. Suite is 116 green (2026-10-14).

- [ ] **39 Lekki Headmaster questions still staged** in `data/inbox/lekki-headmaster-candidates.json`. Of 77 harvested, 9 were not novel questions (returned to the bank), 15 had truncated stems carrying no question at all, 1 duplicated an existing question with a garbled name, and only 4 could be verified against our own chapter summaries — those 4 joined the novel document (50 -> 54). The rest stay staged: their keys are third-party and our summaries cannot check their detail, so adding them would raise the count without raising trust.
- [x] **v1 key seam (D53, Phase 0+1)** — shipped 2026-10-11 (note: the trailing "file backend still the dev default" was retired by D53-final — runtime is Turso-or-error; file is tests + import-source only). `KeyStore::{list,rotate,reload_if_changed}`, extended `ApiKey` (`account_id/plan/prefix/expires_at`, defaulted), `KeyBackend::{File,Remote}` (async, one shape), `TursoKeyStore` (`turso_serverless`, DDL auto-create, 30s TTL cache, cache invalidation on revoke/rotate), `key list/rotate/import` CLI, config accepts `TURSO_DB_URL`/`TURSO_DB_TOKEN` (+alias warnings, half-creds fall back to file with warning). Verdict met: `cargo build` green, `cargo test` 72/72, clippy clean, live smoke vs **real Turso**: create→`/keys/me` 200→CLI revoke (no restart)→200 within TTL→**401 after TTL**. Known trade-off: cross-process CLI revoke visible within `KEY_CACHE_TTL_SECS` (30s), same-process revokes immediate — plan §11.1.
- [x] ~~**Assemble a paper** (`POST /exams/{exam}/papers`) — **gated on content, not on code** (D41).~~ — **done 2026-10-14 (D69/D70)**: `POST /api/v1/papers/{exam}/{subject}?seed=` serves deterministic, answerless papers with stateless scoring. The old framing ("JAMB needs 180 verified rows") described a whole-exam paper; we assemble **per subject** (D41's 4-subject JAMB mock stays refused), and each subject's own stated size is the bar. **23 of 24 JAMB subjects serve today**, every one labelled `mode: "count"` except mathematics, whose blueprint governs and is short (see below).
- [x] ~~**Launch blocker, one content ask** — music's 40th verified row~~ — **done 2026-10-14**: 3 authored 2025-cohort rows (B-flat transposition, V7 spelling in C, imperfect cadence) took music 39 → **42 verified**, and all **25 JAMB subjects now serve a full-length paper**. The five parked music rows were re-examined first: their figures were **already attached** (inline image marks — the null `image` field made them look missing), so the blocker was never a lost figure but keys we cannot confirm off a 400px scan. Recorded below rather than guessed.
- [ ] **Music: 5 rows parked on scan quality, not on missing figures** — 76294 (chord inversions), 76300 (tonic sol-fa transcription), 76303 (time signature), 76320 (double sharp), 76313 (words set to a melody: unanswerable as served — the stem gives lyrics, and the options differ only in rhythm). Each already carries the source's figure, so each is now reviewable **by anyone who can read sheet music**; a music teacher's pass would return up to 5 rows to the bank. 76320 is the clearest case: the source key says D, which requires a written C double sharp on a ledger line, but the scan shows the note in the space below the bottom line (D double sharp → E) with no ledger — the D45 trap again, so the key stands unconfirmed. **Also 76294** reads nearer `Ia–Vb–Va–Ia` (bass G#) than the source's `Ia–Va–Va–Ia`.
- [x] ~~**Launch blockers, exactly two content asks** — mathematics' 10 questions~~ — **impossible under 2025-only, and the predicate stood down (D71)**. The 6 short topics (binary-operations 2, loci 2, measures-of-dispersion 2, mensuration 1, polynomials 1, representation-of-data 2) are short because the **2025 paper contains no such questions** — we hold all 55 claimed 2025 maths rows the source lists, and those topics hold 0. The blueprint's `need` is a per-paper expectation averaged over 17 papers, so a one-cohort bank can never satisfy it; asking for filler that claims an exam's shape is the D47 failure in topic form. Mathematics now serves a 40-question `mode: "count"` paper, and the readiness endpoint reports `governed: false, cohorts: [2025]` so nobody reads 17/23 as debt. The predicate activates itself when a second cohort lands — no code change.
- [x] ~~**Physics has 102 verified rows with no subtopic tag**~~ — **done 2026-10-14**: all **105** physics rows tagged against real syllabus slugs (84 distinct subtopics, none forced); 37 of 39 topics now carry questions and every row is reachable through the syllabus. Same, smaller and still open: history 21 untagged, use-of-english 13, art 4 — same treatment, same script shape.
- [ ] **Duplicate audit runs on every content change** — `tools/dup_audit.py` (report) and `tools/dup_audit.py --strict` (exit 1) plus `tests/dedup.rs`, which fails the suite on duplicate ids, on two rows sharing a question identity, on same-stem/same-key/different-options, and on any *new* shared-stem pair not reviewed. Four rows were removed 2026-10-14; the two survivors are reviewed pairs. Run the audit after every batch, not just at release.
- [ ] **`Cache-Control: public` on metered `/questions`** — flagged by the Jamb-Lab consumer notes (`docs/JAMB_LAB_NOTES.md` §3): a shared cache could serve paid-tier rows to URL-holders with no key. `private` may match the D27 metering intent. Review the middleware, decide, record.

## Content (English-first, D34)

- [ ] **Blueprint rows for the subjects D70 leaves on the count gate** — literature-in-english measures 34 of 40 seats (85%; the prescribed-texts remainder is unmeasured), so its paper is labelled `count` despite a real topic mix being known; use-of-english states ranges (`range-reported`, no `expected`) across 3 topics of a 60-question paper; biology/chemistry/economics/geography/government/physics are section-level only. Each missing row set flips that subject to `blueprint` mode automatically once the measurement **covers** its paper — the gate is data-driven, so this is blueprint work, not code.
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
