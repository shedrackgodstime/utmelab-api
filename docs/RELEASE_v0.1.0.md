---
name: Quick ship, 2026-10-14
description: v0.1.0 goes out with the content bank complete and the open decisions recorded rather than resolved
---

# Quick ship — v0.1.0

The brief was explicit: ship what exists, work on the rest of the API
afterwards. This records what went out, what was deliberately left open, and
what the first person to look at a problem should know.

## What ships

**The bank**: 2,244 questions, all 2025, all JAMB except one WAEC row and one
with no exam (both withheld or single-row, both documented). 2,186+ verified
rows; the rest are documented parks.

**25 of 25 JAMB subjects serve a full-length paper** through
`POST /api/v1/papers/{exam}/{subject}?seed=` — 40 questions each, English 60.
Answers never ride the paper; `.../score` re-assembles from the seed and marks
only submitted ids. Every paper carries `mode` (`count` today, because the
bank is one cohort — D71).

**Per-subject drills**: `/api/v1/questions` filtered by subtopic, with the
syllabus tree carrying live counts. Physics alone went from 0 rows in any drill
to 105.

**Readiness accounting**: `GET /api/v1/blueprints/{exam}/{subject}` serves
measured per-topic expectations against verified coverage, with provenance per
row and `governed`/`cohorts` so nobody reads coverage as a promise.

## What ships open, on purpose

| # | Open | Why it is fine to ship like this |
|---|---|---|
| 1 | Paper and blueprint endpoints take no API key | They serve stems, never answers, and no key means a consumer can evaluate the product before paying for it. `/questions` — the metered surface — is keyed. Revisit with pricing (O5). |
| 2 | Yoruba has zero headroom (exactly 40/40 verified) and music has +2 | Both serve today. Any park in those two closes their gate, which the 409 says plainly. Build margin deliberately, not by accident. |
| 3 | 34 rows have no subtopic | All 34 have a recorded reason: history 24 (our syllabus source carries no world history), English 6 (no passage in the row), two subjects with no catalog, two with no fitting subtopic. Every one is reported as unattributed rather than filed wrongly. |
| 4 | 13 rows sit in quarantine, 61 are unverified | They do not sell. `/health` carries the withheld count so none of it is silent. |
| 5 | Every paper is `mode: "count"` | One cohort. Blueprint mode activates itself when a second year lands — no code change. |
| 6 | No backup job for Turso | The content tables re-seed from the file in `data/`, and the verification log is in git. The key store does not have this property: **rotate or export keys before trusting Turso with anything you would miss.** |
| 7 | Rate limits at dev defaults (60/min) | Fine for launch traffic; set real values with pricing. |

## What the next person should do first

1. **Turso is the source of truth for the served bank.** If it is lost,
   `cargo run --example seed_questions` rebuilds it from `data/` — file first,
   Turso second, always.
2. **Run `tools/dup_audit.py --strict` after any content change.** One question,
   one row is now a gate, not a promise (`tests/dedup.rs`).
3. **Never author a key a syllabus does not state.** Seven D-rows were ratified
   by this release; the arithmetic in `docs/QUESTION_BANK_DECISIONS.md` is the
   law for anything that follows.