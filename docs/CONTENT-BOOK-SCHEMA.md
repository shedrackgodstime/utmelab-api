# Content Book Schema

Status: Active
Last updated: 2026-11-12

This is the structure of the book we are making. It is a content schema, not
an API schema and not a database schema. Everything we build later, the
storage and the routes and the app, adapts to this. If a shape here is wrong,
we change it here before anything is built on it.

## The hierarchy

```
book                      Secondary Physics
  parts[]                 Part I: Motion and Force
  chapters[]              Forces and Newton's Laws of Motion
    learning_objectives[] what the reader will be able to do
    prerequisites[]       chapter ids this one builds on
    formula_sheet[]       the formulas of the chapter, gathered
    glossary[]            the terms the chapter introduces
    sections[]            the teaching units
      learning_objectives[]
      teaching_text       ordered blocks
      worked_examples[]   a problem, solved step by step
      misconceptions[]    what people get wrong, and the correction
      summary_points[]    what to remember
      exercises[]         practice, with answers and solutions
```

The book does not belong to an exam. An exam refers to a chapter or a
section. Nothing in this document names an exam.

## The book

```jsonc
{
  "book_id": "secondary_physics",
  "schema_version": 2,
  "updated_at": "2026-11-12",
  "title": "Secondary Physics",
  "subject_area": "physics",
  "level": "secondary",                 // secondary | foundation
  "edition": "draft-1",
  "description": "...",
  "parts": [
    {"id": "part-1", "order": 1, "title": "Motion and Force"}
  ],
  "licence": "...",
  "sources": [ ... ]
}
```

A book has one subject area and one level. Parts are optional and are how a
school textbook divides itself. A chapter may sit in a part or sit at the top
level.

## The chapter

```jsonc
{
  "chapter_id": "phy_forces_and_newtons_laws",
  "book_id": "secondary_physics",
  "part_id": "part-1",
  "order": 1,
  "title": "Forces and Newton's Laws of Motion",
  "learning_objectives": [
    {"id": "lo-1", "statement": "Define force as a vector ...", "bloom_level": "understand"}
  ],
  "prerequisites": ["phy_motion_in_a_straight_line"],
  "formula_sheet": [
    {"id": "f-1", "expression": "$F_{net} = ma$",
     "caption": {"text": "Newton's second law", "inline": []},
     "conditions": {"text": "For a system with constant mass", "inline": []},
     "provenance": { ... }}
  ],
  "glossary": [
    {"id": "g-1", "term": "inertia",
     "definition": {"text": "The tendency of a body to resist a change in its velocity.", "inline": []},
     "provenance": { ... }}
  ],
  "sections": [ ... ],
  "sources": [ ... ]
}
```

- **Learning objectives** are the chapter's promise. Each one is a statement
  a reader can be checked against.
- **Prerequisites** name the chapters that come first. A learner who skips
  one is told.
- **The formula sheet** gathers the chapter's formulas in one place with
  their conditions, the way a textbook puts a box of formulae at the end of
  a chapter.
- **The glossary** gathers the terms the chapter introduces.

## The section

The teaching unit. A chapter of five to ten sections, each one to three
readings long.

```jsonc
{
  "id": "sec-2",
  "order": 2,
  "slug": "force-and-the-free-body-diagram",
  "title": "The force concept and the free-body diagram",
  "est_minutes": 20,
  "learning_objectives": [
    {"id": "lo-1", "statement": "Define force as a vector quantity ...", "bloom_level": "understand"}
  ],
  "teaching_text": {"blocks": [ ... ]},
  "worked_examples": [ ... ],
  "misconceptions": [ ... ],
  "summary_points": [ ... ],
  "exercise_ids": ["ex-sec-2-01", "ex-sec-2-02"],
  "provenance": { ... }
}
```

### Teaching text blocks

The vocabulary of the prose. Every block carries an id and a type, and the
types are these and no others.

| Type | Holds | Reads as |
| --- | --- | --- |
| `paragraph` | RichText | the prose |
| `heading` | RichText | a sub heading inside the section |
| `definition` | term, definition | a term and what it means |
| `rule` | statement, conditions, note | a rule with the conditions it holds under |
| `formula` | expression, caption, conditions | a displayed formula |
| `example` | statement, steps, answer | a worked example inside the prose |
| `figure` | asset_url, caption, alt | an illustration with its description |
| `table` | title, rows, alt | a table with its description |
| `list` | ordered, items | a list |
| `callout` | kind, text | a box in the margin: key_concept, warning, law, tip, definition |
| `summary` | points | the summary of the section |
| `exercise_ref` | exercise_id, prompt | a pointer: try this now |
| `glossary_entry` | term, definition | a term defined in place |

```jsonc
{"id": "b-3", "type": "rule",
 "statement": {"text": "Powers with the same base are multiplied by adding the indices.", "inline": []},
 "conditions": {"text": "The bases must be the same.", "inline": []},
 "note": {"text": "Multiplying the indices is the power rule, which is different.", "inline": []}}

{"id": "b-7", "type": "callout", "kind": "key_concept",
 "text": {"text": "A free-body diagram shows only the external forces on one body.", "inline": []}}

{"id": "b-9", "type": "exercise_ref", "exercise_id": "ex-sec-2-01",
 "prompt": {"text": "Try this before you read on.", "inline": []}}
```

### Worked examples

A problem and its solution, in the section that teaches it.

```jsonc
{
  "id": "we-sec-2",
  "statement": {"text": "Two skaters push on a third ...", "inline": []},
  "steps": [{"step_number": 1, "expression": "The figure shows two skaters pushing ..."}],
  "answer": {"text": "$F_1$ and $F_2$, the two external pushes.", "inline": []},
  "provenance": { ... }
}
```

### Misconceptions

What the reader is likely to get wrong, and the correction.

```jsonc
{
  "id": "mis-1",
  "claim": {"text": "$2^3 \\times 2^4 = 2^{12}$", "inline": []},
  "correction": {"text": "The product rule adds the indices ...", "inline": []},
  "provenance": { ... }
}
```

## The exercise

Practice, with an answer and a solution. An exercise without both is not an
exercise.

```jsonc
{
  "id": "ex-sec-2-01",
  "section_id": "sec-2",
  "tier": "core",                 // warm_up | core | stretch
  "kind": "numeric",              // numeric | algebraic | verbal | application | proof
  "difficulty": 3,                // 1 to 5
  "marks": 3,
  "stem": {"text": "...", "inline": []},
  "options": [],                  // for a multiple choice item
  "answer": {"text": "265 N", "inline": []},
  "answer_kind": "expression",    // expression | explanation
  "solution": [{"step_number": 1, "expression": "..."}],
  "hints": [
    {"hint_number": 1, "text": {"text": "Start with F = ma and write down what you know.", "inline": []}}
  ],
  "tags": ["newtons-second-law"],
  "provenance": { ... },
  "solution_provenance": "..."
}
```

**Tier** is how a textbook ladders practice. Warm-up exercises check one
idea, core exercises are the standard work, stretch exercises combine ideas
or go beyond the section. Every exercise has a tier, so a reader can work
down the ladder or start at the stretch tier.

The tier is not a guess. It comes from the grouping the source itself uses:
Conceptual Questions are warm-up, the section exercises are core, and the
multi part problems and the test preparation sets are stretch. A spec may
override any of it.

**Hints** are optional and progressive: the first nudges, the second points
at the method. They are written by us, so they carry our provenance, not the
source's.

## Provenance

Every object that carries content carries where it came from.

```jsonc
{
  "publisher": "OpenStax",
  "title": "College Physics 2e",
  "url": "https://github.com/openstax/osbooks-college-physics-bundle/blob/main/modules/m42069/index.cnxml",
  "locator": "CNXML module m42069, section 'Using the Product Rule of Exponents'",
  "licence": "..."
}
```

- The teaching text, the examples, the misconceptions, the figures and the
  exercises all come from a source, and each carries its own locator.
- The learning objectives, the summary points, the glossary definitions, the
  formula sheet captions and the hints are ours, and they say so by having
  no source or by naming ours.

## The invariants

These are the rules the content has to hold. The validator checks them on
the document, and later the routes will check them on write.

1. A book names no exam. A chapter names no exam.
2. Every content object carries provenance with a publisher, a title, a
   locator and a licence.
3. Every exercise has an answer, an answer kind, a tier, and a solution with
   at least one step.
4. Every exercise has at most three hints, numbered in order.
5. Every section has learning objectives, at least two summary points, and a
   worked example or a reason for having none.
6. Every figure has an asset, a caption and alt text.
7. Every exercise belongs to exactly one section, and that section lists it.
8. Sections are numbered 1 to n with no gaps. Chapters are numbered within
   their book. Exercises are numbered within their chapter.
9. A chapter's formula sheet holds the formulas the chapter teaches, each
   with its conditions.
10. A glossary entry is a term the chapter introduces, defined in one
    sentence.
11. The written style applies to what we author. Quoted source prose keeps
    the source's punctuation.

## The spec and the factory

A chapter is built, not typed. The spec holds everything a human authors,
and the factory assembles the chapter from the spec and the source:

```
data/chapter-specs/<chapter_id>.json     the authored part, the source of truth
data/concepts/*.json                     the source material, with the figures
data/staging/openstax_clean_solutions.json   the solutions, prose apart from maths
        │
        ▼  scripts/build_chapter.py
data/chapters/<chapter_id>.json          the built artifact
        │
        ▼  scripts/validate_chapters.py
0 errors
```

The spec names the source module for each section, the objectives, the
misconceptions, the summary points, the formula sheet, the glossary and the
exam links. It also selects the exercises it wants from the module and says
how hard each one is, and it may promote one solved exercise to the section's
worked example with `worked_from`.

The chapter is generated, so it can never drift from its spec: the quality
workflow rebuilds every chapter and fails if the result differs from the file
on disk.

## The bank and the exam side

A chapter teaches. An exam examines. The two meet in `exam_links`, and the
link carries the questions the bank holds for that exam subtopic.

`scripts/link_bank.py` reads the production bank and writes the question ids
into the spec, then reports the coverage. The spec keeps the truth, so the
chapter rebuilds without a database, and the coverage report is the honest
measure of what the exam side of the book actually holds.

Right now the report says the bank is thin: ten of the twenty two links point
at a subtopic with no questions at all, and the covered subtopics hold one or
two questions each. That is a statement about the bank, not about the
chapters.

## Where we are against this

Two chapters exist today and both were written before this schema was
settled. What they already have:

- nine sections and fifty exercises for the mathematics chapter
- five sections, seventeen figures and sixteen exercises for the physics
  chapter
- learning objectives, worked examples, misconceptions, summary points
- provenance on every object, and every exercise with an answer and a
  solution

What is missing, and what I will add to both:

- **tiers** on every exercise, from the difficulty already assigned:
  difficulty 1 and 2 is warm-up, 3 is core, 4 and 5 is stretch
- **hints**, written for the exercises where a nudge helps
- **formula sheets**, gathered from the formulas the chapter already teaches
- **glossaries**, from the terms the chapter already defines
- **prerequisites**, so the books read in order
- **parts**, where the book divides itself
- **learning objectives per section**, which today sit only on the chapter

That is the work that makes this a schema rather than two good documents.
