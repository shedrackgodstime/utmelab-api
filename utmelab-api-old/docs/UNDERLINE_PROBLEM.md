# The underline problem — 78 unanswerable English questions

**Status:** **backfilled 2026-10-13** — all 78 carry `Underline` marks
(quarantine `underline_missing`: 78 → 0). Rows are answerable as served;
`verified` still requires a human review pass each (D62), which is the
remaining work. **Found:** 2026-10-11, during the English correctness audit.
**Affects:** 78 of 210 Use of English questions (37%, after the 83 novel rows left the bank).

---

## What the problem is

These questions name their target word in the stem and mark nothing in the data:

> Choose the word opposite in meaning to the underlined word:
> The plaintiff made very **cogent** submissions to the trial judge.

The question is asking about one specific word. **We do not store which one.**
Only 10 of the 78 carry any markup at all.

A student sees four options (`persuasive / feeble / lengthy / oral`) and no way
to know that *cogent* is the word in question. Every other word in the sentence
produces a different question with a different answer — for *cogent* the answer
is **feeble**, for *submissions* it would be something else entirely.

**These are not hard questions. They are unanswerable ones.**

## Why it matters more than the raw count suggests

The affected subtopics are the ones with the most questions and the clearest
teaching value:

| subtopic | shape | what the student must know |
|---|---|---|
| antonyms | synonym/antonym of *X* | which word is *X* |
| synonyms | synonym/antonym of *X* | which word is *X* |
| word-stress | stress pattern of a given word | which word is stressed |
| vowels / consonants | same sound as a given word | which sound is underlined |

Without the target, a student can guess with 25% odds. With it, the question
tests what it was built to test. **The bank currently sells a coin flip.**

It also silently depressed our own audit: reading these rows earlier, I inferred
the target from the answer (*cogent* → *feeble*) and thought they were fine.
A reviewer doing that is compensating for a defect in the data, and a student
cannot.

## Why it happened

The source renders emphasis in HTML (`<u>`, `<em>`, or a class). Our harvester
extracts the question as **plain text** and drops the markup, because there is
nowhere in the schema to put it. `clean()` strips tags by design
(`re.sub(r"<[^>]+>", " ", fragment)`).

The same class of loss as the raw-HTML-entities defect we fixed yesterday
(139 questions), one level up: **that one leaked markup into the text, this one
strips it out.**

## Options

### 1. `emphasis: Option<String>` on `Question` — **recommended**

Holds the exact substring to underline. The consumer highlights it.

- Pros: machine-readable, trivial for a client, no parsing.
- Cons: positional drift if the sentence text is ever edited; two ints (span)
  would be stricter but heavier than the use warrants.
- Cost: additive schema change to the D11 constant; 78 backfills.

### 2. Inline markup in `text` (`<u>cogent</u>` or `**cogent**`)

- Pros: no schema change; renders directly; visually unambiguous.
- Cons: every consumer must parse markup out of a field they reasonably expect
  to be plain text; the API contract becomes ambiguous.

### 3. Both

Most robust, most work: 78 field values **and** 78 markup edits **and** 78 parser
concerns to keep them in sync.

**Recommendation: option 1.** By D22 — prefer the option that costs the consumer
less to reason about. A field is actionable; markup is a parsing obligation on
every caller, forever.

## Backfill record (2026-10-13)

All 78 filled by worksheet (`propose` → human read → `apply`), each target
occurring exactly once in its stem (checked programmatically — no
first-occurrence ambiguity anywhere). Groups: 16 antonyms + 16 synonyms
(answer-matched back to the sentence), 6 idiom portions, 38 sound items, 2
emphatic-stress (caps words NEW/YESTERDAY, answer-confirmed), 10 gap-antonyms
(the contrast anchor, e.g. *dogged* — not the gap).

Two recorded limitations, not defects in the marks:

1. **Sound items mark whole words, not letters.** Stems say "the underlined
   *letters* in: boot" — the letter-level target died in the harvest. The
   recoverable, reviewable unit is the word; claiming `oo` would be guessing.
2. **`t76545` had a wrong key, now corrected.** "Same vowel sound as in:
   bought" keyed *son* (/bɔːt/ vs /sʌn/ share nothing); corrected to *port*
   with a rewritten explanation, old key documented in its trap. The mark
   (`bought`) stood throughout. Lesson kept: check the answer by computing
   it — the batch also parked `t74853` (`wound` noun/verb ambiguous, no
   context) rather than verdict it.

## Backfill method (as applied — difficulty was not uniform)

| group | how the target is recovered | effort |
|---|---|---|
| synonyms / antonyms | the answer is a near-meaning (or opposite) of the target, and the target is a distinctive word in the sentence | reliable; the answer itself identifies it |
| sentence interpretation | "the underlined portion" — usually recoverable by matching the answer back to the sentence | per-item reading |
| word stress | target is the **word**, answer is a **different word** with the stressed syllable marked | per-item reading |
| vowels / consonants | target is the **word**, answer is a different word sharing its sound | per-item reading |

So roughly half backfill semi-automatically and half need reading. None of it
can be done by guessing, which is the point — the harvest brought us the
questions but not the emphasis, and the emphasis is part of the question.

## Related defects found in the same pass (all resolved — record kept)

- **6 novel questions sat in the English bank** — stems beginning "This question
  is based on …The Lekki Headmaster…", missed by the D35 sweep (they named the
  *novel*, not a character). Moved out 2026-10-11 with the 45-row rescue; the
  guard test now scans every page.
- **5 duplicate stems** within the English bank — resolved (quarantine
  `duplicate_stem` is clean today).
- **1 question with 5 options** where JAMB sets 4 (D46) — reviewed, kept with
  its era note; JAMB is 4 × 2.5.
- **4 questions where two options differ only in capitalisation** — the
  word-stress items. Harmless in rendering, a trap for any consumer that
  case-folds.

## What "correct English" therefore requires, in order

1. **Decide the emphasis representation** (option 1 recommended). — **decided 2026-10-11 (D54) as `emphasis: Option<String>`, superseded 2026-10-12 (D60) by an `Underline` mark in `RichText.inline`, implemented 2026-10-13 (P1).**
2. **Backfill 78 targets as `Underline` marks** — semi-automatic for synonyms/antonyms, read by hand
   for stress and sound items (`python3 tools/propose_emphasis.py propose/apply`).
3. **Move the 6 novel questions out** into the novel document. — **done
   2026-10-11** (45-row rescue + guard fix).
4. **Resolve the 5 duplicate stems and the 5-option question.** — **done**
   (quarantine clean on dupes; the 5-option row keeps its era note per D46).
5. **Then verify and explain** — which is the ordinary work. Unblocked now:
   review batches via `review.py`, one Human/Pass log row at a time (D62).

`verified` on any of the 78 before its mark landed would have been a lie;
the loader enforced it (D57, now D62 derivation). Marks are in since
2026-10-13 — what remains is review, not repair.