# Review method — how content batches are worked (D62 operators' notes)

**Status:** living note, 2026-10-13. Written after ~1,000 verified rows so the
next reviewer (human or model) repeats what works and skips re-learning it.
The decision log stays the law; this is the trade craft.

## 0. Pull first, always

`git pull origin main` before triage **and** before push. Remote moves
mid-batch (maths tagging, cloze recovery both landed mid-batch); rebase,
re-run gates, then push. Never force-push content.

## 1. Triage (mechanical, scripted)

1. `python3 tools/review.py stats` — per-subject verified/quarantined.
2. One subject at a time, id-sorted, via `review.py` flag logic
   (`flags_for`: same predicates as `src/quarantine.rs`).
3. Split the batch into: **workable** (explained or authorable, unflagged),
   **figure rows** (need §2), **parked** (§5). Never mix verdicts.

## 2. Figures — read by eye, never by faith

Every `Image` mark carries its source URL. The procedure, in order:

1. `curl` the URL from the mark. If it 404s or returns HTML, the row stays
   parked (mirror job, D55) — no explanation is authored for a figure nobody
   can see (`shm_002` rule).
2. **Read the figure yourself and recompute the key from it.** Examples that
   actually happened: concentric circles = straight conductor (74358);
   Z ≈ 163.5 Ω from R/X_L (74489); Punnett 1:2:1 (74648); XOR symbol (67763);
   snail shell vs nerve centre told apart only by zoom (74496/74497).
3. Record the reading **inside the explanation body** ("From the figure: …"),
   so a later reviewer can check the figure claim without re-fetching.
4. Zoom when labels are small (`74679` read 2 Ω, not 3 Ω — the wrong read
   would have certified a wrong key). If zoom cannot settle it, park the row
   (`74505`: too rough to confirm liver).
5. A figure that underdetermines the answer parks the row with the arithmetic
   shown (`74492`: statics gives T = 20 N vs recorded 19.24, no weight
   stated). Never bend a key to fit pixels.

## 3. Keys — computed, never trusted (D45)

Recompute every key from first principles: resultants, gas laws, half-life,
Punnett squares, Boolean truth, constitutional dates against sources. The
third-party key is evidence, not review — this practice has caught wrong keys
at a steady rate (`t76545`, `74536`, `76617`, `64138`, `64385`, `64413`).

**Key-correction protocol (D45 pattern):** change `answer`, rewrite the
explanation, and document the old key **in the trap** ("Recorded X;
corrected to Y because …"). The trap is where a student meets the old
mistake, so it is where the correction lives too.

## 4. Explanations — three fields, plain text (D17/D56/D60)

- `key_point`: one line, the thing to remember (flashcard teaser).
- `body`: the working, with the formula or rule applied at the point of use.
  LaTeX `\(…\)` passes through as characters; **no `<`, `&entity;` or markup
  ever** — the D56 gate refuses the whole bank on one stray bracket (it
  caught authored prose twice).
- `trap`: the tempting wrong answer and why it is wrong. No trap in the
  question → `trap: null`, never padding.
- All three are `RichText`; marks stay empty unless the prose needs one.
  Never invent emphasis to fill the array.

## 5. Park rules — a parked row is a decision, not a delay

Park (with reason in HANDOFF) when: no correct option exists (`74548`,
`74624`); options lack the true case (`74216`); stem underdetermines the
answer (`74492`, `74417`, `74505`); two options are both correct (`64424`);
figure unreadable or missing (`shm_002`). **Never verdict a parked row, and
never author content to un-park one** (no written passages behind
`claimed_paper` keys — CLOZE_PROBLEM §6).

## 6. Tags ride review (D16)

Every authored row gets `subtopic_id` in the same pass — the reviewer already
read the stem. Rules: the slug must exist (the loader refuses otherwise —
it caught topic-slugs-as-subtopics twice); tag the finest fitting unit, not
the topic; no fitting path → leave null and record it (`74512`), never force
a mistag. A mistag is a wrong drill path served with confidence.

## 7. Typos — minimal, recorded

Fix only what changes answerability (`C0` → `CO`, `lumber` → `lumbar`,
`Crashinng` → `Crashing`), one line in the commit and HANDOFF. Never
rephrase stems.

## 8. Verify through the tool, then gates

1. `review.py verify <id> --by <batch>` — it refuses flagged and
   explanationless rows; zero refusals is the expectation, any refusal stops
   the batch.
2. `cargo test` + `clippy` + `fmt` + `quarantine` (count must not rise).
3. Counts: `review.py stats` before/after in the commit message and HANDOFF.
4. One subject per commit; WORKING TREE and HANDOFF in the same commit so the
   map never lags the bank.
