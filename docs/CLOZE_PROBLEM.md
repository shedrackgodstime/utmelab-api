# The cloze problem — 10 unanswerable English questions

**Status:** found 2026-10-13. **No D-row yet, no data changed.** The 10 rows
are still servable. Read before touching Use of English.

**Affects:** 10 of 2,247 questions (0.4%). All `source: claimed_paper`,
all `verified: false`, all `exam: JAMB`, all year 2025.

Discovered while deepening the English catalog — the candidate `cloze`
subtopic failed a row-count check, and the reason turned out to be that
most of its rows cannot be attempted at all.

---

## 1. What they are

`q_claim_2025_english-language_74774` … `74783`. The stems are the whole
question:

```
74774  "Fill the gap labelled 6"
74775  "Fill the gap labelled 7"
…
74783  "Fill the gap labelled 15"
```

Options are four words each, and the keys are consistent enough to
reconstruct the topic:

| gap | options | key | gap | options | key |
|---|---|---|---|---|---|
| 6 | Unit / **Council** / Department / Committee | b | 11 | **Charter** / league / unit / directorate | a |
| 7 | relation / affairs / **peace** / relationship | c | 12 | **threat** / agitation / violence / fear | a |
| 8 | safety / unity / **security** / progress | c | 13 | people / states / entity / **parties** | d |
| 9 | member / personnel / **members** / states | c | 14 | **settlement** / agreement / consent / condition | a |
| 10 | assent / **vote** / consent / voice | b | 15 | rules / **sanctions** / order / discipline | b |

It is a cloze passage about the United Nations: *Security Council, peace,
security, members, vote, charter, threat, states, settlement, sanctions.*
None of that is stated in the row.

## 2. Why they cannot be answered

A cloze question is not the gap — **the gap is a pointer into a passage we do
not hold.** Without the surrounding text, "Fill the gap labelled 9: member /
personnel / members / states" is a coin flip. A student scores by luck, and a
paid consumer is being sold a guess.

This is the same class as the 78 underline rows (`UNDERLINE_PROBLEM.md`):
content that references a stimulus the bank does not carry. Those were
unanswerable because the target word was missing; these are unanswerable
because the passage is missing. The difference is only that 10 rows are
smaller than 78, so nobody went looking.

## 3. The passage was never captured — this is not a later loss

Checked against the raw harvest at
`data/inbox/archive/english-language-2025.json`:

```json
{ "id": "q_claim_2025_english-language_74774",
  "text": "Fill the gap labelled 6",
  "passage_id": null, "section": null,
  "explanation": null, "verified": false }
```

The harvester emitted them with no `passage_id` and no `section`. Nothing was
dropped afterwards — it was never taken.

Nor can it be matched to a passage we already hold. `data/passages.json` has
five; the two `Cloze` ones are both **authored** and unrelated:

| passage | kind | content | used by |
|---|---|---|---|
| `psg_jamb_2025_eng_cloze_1` | Cloze | a boy born before his parents married | `cloze_001` |
| `psg_jamb_2025_eng_cloze_2` | Cloze | Nigerian public libraries | `cloze_002–004` |

A UN passage is simply absent.

## 4. Two further facts that matter

**Gaps 1–5 are not in the bank at all.** We hold 6–15 of a 15-gap passage.
So even a perfect recovery of the passage yields a 10-gap cloze, not a
15-gap one.

**They are servable.** `verified` is a filter, not a gate (D45/D51) — an
unverified row is still returned by `/questions`. So these ten ship to paid
consumers today, in a subject that is **compulsory in the completed JAMB
paper**.

## 5. Why the harvester let them in

`FIGURE_HINT` (`tools/harvest.py`) already refuses any row whose stem says
"diagram below" and carries no image — a mechanical integrity rule, counted
like every other refusal (D51). There is **no equivalent for cloze**. A stem
referencing a numbered gap is exactly as unanswerable as a stem referencing a
missing diagram, and the rule that catches one does not catch the other.

## 6. Options

| | action | cost | risk |
|---|---|---|---|
| **A** | **Drop the 10 rows** | bank 2,247 → 2,237 | loses 10 claimed_paper rows we might recover later; recoverability unknown |
| **B** | **Author a UN passage** to fit gaps 6–15 | cheap | **No.** The rows are `claimed_paper`. An authored passage behind a claimed-paper question is D47/D48's fabrication — a stimulus we wrote would make a third-party key look sourced |
| **C** | **Recover the real passage** by re-harvesting the source page | unknown; source is third-party | may not exist in retrievable form |
| **D** | **Add the missing refusal rule** — a stem referencing a gap with no `passage_id` is refused at the import gate, counted (D51) | small; mirrors `FIGURE_HINT` | none; prevents recurrence |

**Recommended: D + A, with C attempted first.**

D is the actual fix and is independent of what we do with the ten. A
recovers the content if C pans out; if C fails within a stated attempt, A
makes the bank honest. B should be ruled out explicitly, because it is the
cheap option and it is the wrong one.

## 7. Open, needs someone who knows

- Is the UN passage recoverable from the harvest source?
- If not, are these 10 rows better dropped, or kept-but-withheld (a
  `withheld` concept already exists for the unassigned-exam fixture, D21/D58)?
- Does the harvest source's Use of English page expose its passages at all —
  if it does, this is a harvester bug, not a content problem

## 8. Do not

- **Do not author a passage to fit these rows.** See B.
- **Do not tag them to a `cloze` subtopic** while they are unanswerable.
  A drill path advertising 10 of 14 rows that cannot be attempted is worse
  than no drill path. This is why no `cloze` subtopic was added.
- **Do not count these as verification work.** They cannot be verified — the
  answer is not checkable without the stimulus. `verified` stays false, and
  `review.py verify` should refuse them the way it refuses quarantined rows
  (D57).