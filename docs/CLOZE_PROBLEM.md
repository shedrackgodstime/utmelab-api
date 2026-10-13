# The cloze problem — 10 unanswerable English questions

**Status: RESOLVED 2026-10-13. Option C succeeded — the passage was recovered.**
The 10 rows are now linked to `psg_jamb_2025_eng_cloze_3`, tagged to a new
`cloze` subtopic, and answerable. Option D (the missing refusal rule) shipped
in `tools/harvest.py` as `CLOZE_HINT`. Options A and B were not needed and B
was never acceptable.

**They remain `verified: false`.** D62 lets only a `Human/Pass` flip that flag,
and the recovered passage makes them checkable for the first time — they
belong in the next English review batch, not in an agent's hands. See §9.

**Affects:** 10 of 2,247 questions, `source: claimed_paper`, `verified: false`,
`exam: JAMB`, year 2025. Originally found 2026-10-13 while deepening the
English catalog — the candidate `cloze` subtopic failed a row-count check, and
the reason turned out to be that most of its rows could not be attempted.

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

---

## 9. Resolution

**The passage was on the source page the whole time.** `harvest.py` never read
it. Each question page carries a `ref` object in the Nuxt payload holding the
passage text; the harvester only ever read the question and its options, so
`passage_id` was emitted as `null` for all ten.

Recovered from `myschool.ng/classroom/english-language/74774…74783` — all ten
pages carry a **byte-identical** passage of 1,399 characters, containing gaps
6–15 with their options inline.

**Gaps 1–5 never existed.** The earlier worry in §4 was wrong. JAMB's Use of
English Paper 1 sets one cloze passage of 10 items; the source numbers them
6–15. We hold all ten, so this is a complete cloze, not a fragment.

**Stored as** `psg_jamb_2025_eng_cloze_3`, title `Passage C`, with each gap
reduced to the house `....` marker. The option lists are stripped — leaving
them in would print every answer inside the stimulus, which is why the passage
could never have been stored raw.

**All ten keys check out against the recovered stimulus.** Each is forced by
its context rather than chosen from among four:

| gap | context | key |
|---|---|---|
| 6 | "The Security …" | **Council** |
| 7 | "maintenance of international … and" | **peace** |
| 8 | "… and …" (completing "peace and ___") | **security** |
| 9 | "It has fifteen …" | **members** |
| 10 | "Each Member has one …" | **vote** |
| 11 | "Under the … , all Member States" | **charter** |
| 12 | "existence of a … to the peace" | **threat** |
| 13 | "It calls upon the … to a dispute" | **parties** |
| 14 | "terms of …" | **settlement** |
| 15 | "resort to imposing …" | **sanctions** |

10/10 of our recorded keys match the source's own option list for the same
gap. That is the first time these rows have been checkable at all.

**`CLOZE_HINT` shipped** in `tools/harvest.py`, refusing at the harvest gate
any row whose stem asks the reader to fill a gap when no passage was captured —
the exact counterpart of `FIGURE_HINT`. Verified against eight stem shapes:
fires on "Fill the gap labelled 6", "Fill in the gap labelled 11", "Choose the
option that fills the blank", "complete the passage"; stays silent on
"Rationalise the denominator", "Find the sum of the first n terms", "Choose
the word opposite in meaning to the underlined word".

**Still open:** the `cloze` subtopic exists and holds 10 answerable rows, so
the §6 warning no longer applies — but the ten carry no explanations. They
should pick them up with the next English review batch, which is also when a
human can set `verified`.