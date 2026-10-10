---
title: Finding questions
description: Drill a subtopic, or take a whole subject.
---

Every response is **paged** and **withholds the answer** unless you ask. See
[Pagination](/docs/guides/pagination/).

## Drill one subtopic

The smallest, most useful unit. A subtopic with twenty questions behind it is a
twenty-minute sitting, which is what a weak spot actually needs.

```bash
curl "https://api.utmelab.com/api/v1/questions?subtopic=change-of-bases" \
  -H "X-API-Key: $UTMELAB_API_KEY"
```

## Take a whole subject

Scope by exam **and** subject — the exam is part of a subject's identity:

```bash
curl "https://api.utmelab.com/api/v1/questions?exam=JAMB&subject=mathematics&per_page=40" \
  -H "X-API-Key: $UTMELAB_API_KEY"
```

## Only verified questions

`verified=true` narrows to questions a human has checked — question, answer and
explanation. It is false by default and most questions start that way, so **do not leave
it off in production** if wrong answers would hurt your users.

```bash
curl "https://api.utmelab.com/api/v1/questions?exam=JAMB&subject=physics&verified=true" \
  -H "X-API-Key: $UTMELAB_API_KEY"
```

## Getting the answer

**The answer and the explanation are withheld by default.** A quiz consumer needs the stem
first, and an answer that rides along in a default payload gets rendered by somebody,
eventually, by accident.

```
?include_explanation=true
```

```json
{
  "id": "q_jamb_2025_math_surds_001",
  "text": "Rationalise the denominator of \\(\\dfrac{6}{\\sqrt{3}}\\).",
  "options": [
    { "id": "a", "text": "2" },
    { "id": "b", "text": "\\(2\\sqrt{3}\\)" },
    { "id": "c", "text": "\\(3\\sqrt{2}\\)" }
  ],
  "answer": "b",
  "explanation": {
    "key_point": "To rationalise, multiply numerator and denominator by the surd itself.",
    "body": "## Working\n\n$$…$$",
    "trap": "\\(2\\) comes from dividing 6 by 3 without carrying the surd down."
  }
}
```

Reveal it after submission — never before.

## Options are ids, labels are positions

`answer` is an **option id**, never a letter and never an index. Option ids are stable
identity; the labels a student sees (A, B, C…) are assigned from array position at render
time.

That means you can reorder or shuffle options and the answer stays correct without any
remapping on your side.

## Maths and LaTeX

`text` and option texts may carry LaTeX: `\\(inline\\)` or `$$display$$`. The same
convention is used in explanations. Render it with KaTeX or MathJax.

## Passages

Questions that belong to a shared stimulus carry a `passage_id`. Fetch the passage once
and render it above the question:

```bash
curl https://api.utmelab.com/api/v1/passages/{id}
```
