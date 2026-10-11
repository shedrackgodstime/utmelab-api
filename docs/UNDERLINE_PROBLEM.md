# The underline problem — 78 unanswerable English questions

**Status:** open. **Found:** 2026-10-11, during the English correctness audit.
**Affects:** 78 of 282 Use of English questions (28%).

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

## Backfill difficulty is not uniform

| group | how the target is recovered | effort |
|---|---|---|
| synonyms / antonyms | the answer is a near-meaning (or opposite) of the target, and the target is a distinctive word in the sentence | reliable; the answer itself identifies it |
| sentence interpretation | "the underlined portion" — usually recoverable by matching the answer back to the sentence | per-item reading |
| word stress | target is the **word**, answer is a **different word** with the stressed syllable marked | per-item reading |
| vowels / consonants | target is the **word**, answer is a different word sharing its sound | per-item reading |

So roughly half backfill semi-automatically and half need reading. None of it
can be done by guessing, which is the point — the harvest brought us the
questions but not the emphasis, and the emphasis is part of the question.

## Related defects found in the same pass

- **6 novel questions still sit in the English bank** — their stems begin
  "This question is based on Kabir Alabi Garba's The Lekki Headmaster…". They
  escaped the D35 sweep because they name the *novel*, not a character.
  (The guard test that should have caught them only scanned page 1 of the
  bank; that is fixed.)
- **5 duplicate stems** within the English bank.
- **1 question with 5 options** where JAMB sets 4 (D46).
- **4 questions where two options differ only in capitalisation** — the
  word-stress items. Harmless in rendering, a trap for any consumer that
  case-folds.

## What "correct English" therefore requires, in order

1. **Decide the emphasis representation** (option 1 recommended).
2. **Backfill 78 targets** — semi-automatic for synonyms/antonyms, read by hand
   for stress and sound items.
3. **Move the 6 novel questions out** into the novel document.
4. **Resolve the 5 duplicate stems and the 5-option question.**
5. **Then verify and explain** — which is the ordinary work, and which is
   currently blocked on step 1.

Until step 2 lands, **`verified: true` on any of these 78 would be a lie**,
because a reviewer cannot answer the question as served.