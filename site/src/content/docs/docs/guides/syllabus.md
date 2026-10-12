---
title: Syllabus and coverage
description: Topics, subtopics, and whether you can practise them.
---

## The whole tree in one call

```bash
curl https://api.utmelab.com/api/v1/exams/JAMB/subjects
curl https://api.utmelab.com/api/v1/subjects/JAMB/use-of-english/syllabus
```

```json
{
  "exam": "JAMB",
  "subject": { "slug": "use-of-english", "name": "Use of English", "is_compulsory": true, "full_exam_questions": 60 },
  "topics": [
    {
      "slug": "comprehension",
      "name": "Comprehension and Summary",
      "order": 1,
      "weight": 25,
      "question_count": 148,
      "subtopics": [
        {
          "slug": "fiction",
          "name": "Fiction",
          "question_count": 63,
          "objectives": ["Identify the writer's attitude towards a character in a passage"]
        }
      ]
    }
  ],
  "summary": {
    "topics": 23,
    "topics_with_questions": 23,
    "subtopics": 62,
    "subtopics_with_questions": 58,
    "questions": 4370
  }
}
```

Every node carries **coverage**: `question_count` on topics and subtopics, and a summary
telling you how much of the syllabus you can actually practise.

That pairing is the point of the endpoint — *what you must be able to do*
(`objectives`, `weight`) beside *what you can drill right now* (`question_count`).

## Subject names belong to their exam

| Concept | JAMB | WAEC | NECO |
|---|---|---|---|
| English | `use-of-english` | `english-language` | `english-language` |
| Mathematics | `mathematics` | `general-mathematics` | `mathematics` |
| Art | `art` | `visual-arts` | `visual-arts` |
| Accounting | `principles-of-accounts` | `financial-accounting` | — |

These are **different subjects**, not aliases of one concept. JAMB genuinely writes *Use
of English*; WAEC genuinely writes *English Language*. Both are true, so we store both and
the exam is part of a subject's identity.

The practical consequence: asking for `/subjects/WAEC/use-of-english` is a **404**, not a
redirect. Look the subject up under the exam you are building for.

`is_compulsory` and `full_exam_questions` are per-exam for the same reason — Use of
English is compulsory in all three, but WAEC's *General Mathematics* is compulsory while
JAMB's *Mathematics* is an elective, and WAEC English Paper 1 has 80 questions where JAMB
has 60.

## Topics come from the official syllabus

Topic names are taken verbatim from each exam's published syllabus, so what you show a
student is what they were told to revise. Subtopics exist only where there are enough
questions to drill, and a topic with no questions does not appear at all.

## Marks are not flat

Use of English is weighted per section — a comprehension answer is worth 3, a cloze answer
2, an oral-forms answer 1, while other subjects are a uniform 2.5. Every question carries
its own `marks`; do not assume they are equal.
