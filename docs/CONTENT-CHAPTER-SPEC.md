# Content Chapter Spec: exam-independent textbook chapters

Status: Active
Last updated: 2026-11-12

This document defines what a chapter is, how it is grounded, and how an exam
refers to it. It replaces the exam-scoped note model described in
`docs/CONTENT-WORKFLOW-CONTRACT.md` for teaching content.

## Why this exists

The note model in production is keyed by placement:

```
topic_notes(id, exam, subject, topic_slug, subtopic_slug, ...)
```

`exam` is `NOT NULL`. So a note belongs to an exam, and the same idea must be
authored again for the next exam. The production numbers show the cost:

- 26 notes for 3,870 questions, and 184 questions (4.8%) under any note.
- 1,461 topics split into 583 JAMB and 878 WAEC rows with zero shared
  slugs, while 17 subject slugs are shared between the two exams.
- 23 question texts duplicated across JAMB and WAEC.
- 7 WAEC notes whose subtopic slugs match no question at all.
- 373 notes staged locally, every one of them with `linked_question_ids: []`.

The direction of ownership is the fix: **a textbook owns the content, an exam
references it.** A chapter is a piece of a book. An exam says which chapters
it examines, with what weight, and which of its own past questions test them.

## The document

One JSON file per chapter, in `data/chapters/<chapter_id>.json`.

```jsonc
{
  "chapter_id": "math_laws_of_indices_and_surds",
  "schema_version": 1,
  "updated_at": "2026-11-12",
  "title": "Laws of Indices and Surds",

  "book": {
    "id": "secondary_mathematics",
    "title": "Secondary Mathematics",
    "subject_area": "mathematics",
    "level": "secondary",
    "edition": "draft-1"
  },

  "learning_objectives": [
    {"id": "lo-1", "statement": "...", "bloom_level": "understand"}
  ],

  "sections": [
    {
      "id": "sec-1",
      "order": 1,
      "title": "Index notation and what a power means",
      "est_minutes": 7,
      "teaching_text": {"blocks": [ ... ]},
      "worked_examples": [ ... ],
      "misconceptions": [ ... ],
      "summary_points": [ ... ],
      "practice_exercise_ids": ["ex-01", "ex-02"],
      "provenance": { ... }
    }
  ],

  "exercises": [
    {
      "id": "ex-01",
      "section_id": "sec-1",
      "kind": "numeric",
      "difficulty": 1,
      "marks": 1,
      "stem": {"text": "...", "inline": []},
      "answer": {"text": "...", "inline": []},
      "answer_kind": "expression",
      "solution": [{"step_number": 1, "expression": "..."}],
      "tags": ["indices"],
      "provenance": { ... },
      "solution_provenance": "..."
    }
  ],

  "exam_links": [
    {
      "exam": "JAMB",
      "subject": "mathematics",
      "topic_slug": "indices-logarithms-and-surds",
      "subtopic_slug": "laws-of-indices",
      "weight_pct": null,
      "expected_count": null,
      "source_locator": "production catalog topic and subtopic (read-only fetch YYYY-MM-DD)",
      "question_ids": ["q_authored_math_indices_001"]
    }
  ],

  "sources": [ ... ]
}
```

### Rules on the shape

- The chapter root must not carry `exam`, `subject`, `topic_slug`,
  `subtopic_slug` or `placements`. A chapter that names an exam is exam-scoped
  content, which is what this model exists to remove.
- `exam_links` is the only place an exam may appear on a chapter.
- `sections[].order` is 1..n with no gaps and no repeats.
- Every exercise belongs to exactly one section, and every section lists its
  own exercises in `practice_exercise_ids`.
- `sources` lists the sources for the teaching content. Every section, worked
  example, misconception and exercise also carries its own `provenance`.

## Teaching text blocks

Block types are the ones the concept documents already use: `paragraph`,
`definition`, `formula`, `table`, `list`, `summary`, plus `example` and
`exercise` inside a section's arrays.

```jsonc
{"id": "b-1", "type": "paragraph", "content": {"text": "...", "inline": []}}
{"id": "b-2", "type": "definition", "term": {...}, "definition": {...}}
{"id": "b-3", "type": "formula", "expression": "a^m \\times a^n = a^{m+n}",
 "caption": {...}, "conditions": {...}}
{"id": "b-4", "type": "figure", "asset_url": "images/phy_m42069_Figure_04_01_02.jpg",
 "caption": {...}, "alt": "...", "licence": "..."}
```

A figure carries the asset, its caption and its alt text. Alt text is not
optional: a learner using a screen reader gets the caption and the
description, and a learner who cannot see the figure still learns from it.

Text is RichText: `{"text": "...", "inline": []}`. Inline offsets are Unicode
scalar offsets into the owning text, `start` inclusive and `end` exclusive.
No HTML, no Markdown.

## Exercises

An exercise without an answer and a solution is not an exercise. Every
exercise carries:

- `stem`: the question, in RichText.
- `answer`: the answer as the source states it. `answer_kind` is `expression`
  for a value, `explanation` for a spoken answer.
- `solution`: numbered steps. The steps come from the source's own solution.
- `kind`: `numeric`, `algebraic`, `verbal` or `application`.
- `difficulty`: 1 (recognition) to 5 (multi-step combination). This is
  editorial judgement, not a fact from the source.
- `marks`: the marks the exercise is worth. Also editorial.
- `tags`: the skills it exercises, used for selection and coverage reporting.

An exercise may carry `answer_note` when the source states the value before
the commentary, so a reader can see why the answer was taken from that line.

### Quoted text and authored text

The style rules apply to what we author: learning objectives, misconceptions,
summary points, and anything else we write. Teaching text is the source's own
prose, quoted with its provenance, and it keeps the source's punctuation. An
em dash in a quoted textbook passage is not our writing.

## Grounding

The rules in `docs/CONTENT-WORKFLOW-CONTRACT.md` still hold and are not
optional:

- **No invention.** No fact, figure, example, answer or exercise that is not
  in a source. Restructuring source material is allowed; adding to it is not.
- **Provenance everywhere.** Every section, worked example, misconception and
  exercise names a publisher, a title, a locator and a licence.
- **Honest status.** When a source's licence is uncertain, record it as
  uncertain. Do not guess.
- **Exam facts stay on the exam side.** Examiner traps, mark schemes and
  recall items written in exam language belong to an exam link or a separate
  revision pack, not to the chapter.

## Exam links

An exam link says how one exam relates to this chapter.

- `exam`, `subject`, `topic_slug`: required, and they must exist in the
  production catalog.
- `subtopic_slug`: the production subtopic, or null when the chapter maps to
  a whole topic.
- `weight_pct`, `expected_count`: the exam's weighting, when it is known.
  Null means not known, which is different from zero.
- `status`: `covered`, `partial`, or `not_catalogued`. A link with no
  `topic_slug` is only honest when the exam's catalog for that subject has
  not been built yet, and then the status must be `not_catalogued`.
- `source_locator`: where the mapping came from, for example the production
  catalog read on a given date.
- `question_ids`: the exam's own questions that test this chapter. These stay
  in the exam's bank; the chapter does not own them.

## Identifier conventions

- `chapter_id`: `<subject_area>_<topic>` in lower snake case, for example
  `math_laws_of_indices_and_surds`.
- Section ids: `sec-<n>`. Exercise ids: `ex-<section>-<nn>`, unique in the
  chapter.
- Book ids: `<level>_<subject_area>`, for example `secondary_mathematics`.
- Concept ids are unchanged, so a chapter can cite the concepts it was built
  from.

## Workflow

1. Build or fetch the sourced concepts for the topic.
2. Write the chapter: learning objectives, sections, teaching text, worked
   examples, misconceptions, exercises with answers and solutions.
3. Pull exercises and their solutions from the source. For OpenStax CNXML,
   run `python3 scripts/scrape_openstax_solutions.py` first: the concept
   scraper folds prose into the mathematics, and this script keeps them apart
   so a solution reads as steps. The same scripts repair the way OpenStax
   splits a value across MathML nodes, so "2 . 64 x 10^7" comes out as
   "2.64 x 10^7".
4. Validate: `python3 scripts/validate_chapters.py` must report 0 errors.
5. Review the rendered chapter by reading it end to end. A validator cannot
   tell you that a chapter teaches badly.
6. Add exam links against the production catalog, read only.

## Definition of done

- [ ] The chapter root names no exam.
- [ ] Every section, worked example, misconception and exercise carries
      provenance with a locator and a licence.
- [ ] Every exercise has an answer, an answer kind, and a solution with at
      least one step.
- [ ] Every section has learning objectives behind it, at least two summary
      points, and at least one worked example, or a
      `no_worked_example_reason` saying why the section has none.
- [ ] Every exercise is listed by the section it belongs to.
- [ ] `scripts/validate_chapters.py` reports 0 errors.
- [ ] A reader who has not taken the exam can learn the topic from the
      chapter alone.
- [ ] Exam links resolve against the production catalog.

## The exam side: where exam-only artefacts live

Content teaches. An exam tests. An artefact belongs to the exam when it is
only true inside that exam's world: paper style, mark allocation, what bit
candidates last year, how the paper is weighted. It belongs to the chapter
when it is true of the subject matter, whoever examines it.

The exam side is not a dumping ground and it is not a footnote on the
chapter. It is a set of objects owned by an exam, each pointing at the chapter
section it examines.

### The objects

| Object | Belongs to | Holds | Points at |
| --- | --- | --- | --- |
| `exam_syllabus_map` | exam | what the exam examines, with weight, expected count, syllabus version and locator | `chapter_section_id` |
| `exam_trap` | exam | a misconception candidates hold, how the paper shows it, the past paper that shows it | `chapter_section_id` |
| `exam_recall_check` | exam | a practice item in the exam's own wording, with an answer and an explanation | `chapter_section_id` |
| `exam_task` | exam | a theory or essay question with its marking method, formulation bridge, examiner report, diagram rubric and penalties | `chapter_section_id` |
| `exam_paper_plan` | exam | the assessment plan for a paper: sections, paper size, percentage ranges, expected counts, method and confidence | `chapter_section_id` |
| `exam_item` | exam | a question in the paper, with year, paper and number | `chapter_section_id` |

Every one of them carries the exam, and every one of them carries the chapter
section it belongs to. The chapter never references an exam object; the
reference always points one way, from the exam to the chapter.

### Shapes

```jsonc
// exam_syllabus_map
{"exam": "JAMB", "subject": "mathematics", "topic_slug": "indices-logarithms-and-surds",
 "subtopic_slug": "laws-of-indices", "chapter_section_id": "sec-2",
 "weight_pct": null, "expected_count": null, "syllabus_version": "2024",
 "source_locator": "production catalog topic and subtopic (read-only fetch YYYY-MM-DD)",
 "status": "covered"}

// exam_trap
{"id": "trap_jamb_math_ap_nth_term",
 "exam": "JAMB", "subject": "mathematics",
 "topic_slug": "progression", "subtopic_slug": "sum-of-arithmetic-progression-a-p",
 "chapter_section_id": "sec-2",
 "misconception": "Using 'n' instead of 'n - 1' in the formula: writing T_n = a + nd.",
 "correction": "The first term corresponds to n = 1, where (1 - 1)d = 0. Using 'nd' advances the sequence by one step.",
 "signal": "the option is offered as the last term rather than the nth term",
 "paper_evidence": {"exam": "JAMB", "year": 2023, "paper": 1, "question_number": "18",
                    "source": "claimed_paper"},
 "frequency": "recurring"}

// exam_recall_check
{"id": "rc_jamb_math_ap_01", "exam": "JAMB", "subject": "mathematics",
 "chapter_section_id": "sec-2",
 "stem": {"text": "Find the 15th term of the sequence 7, 11, 15, 19, ...", "inline": []},
 "options": ["63", "59", "67", "71"], "answer": "a",
 "explanation": {"text": "Here a = 7, d = 4, n = 15. T_15 = 7 + (15 - 1) * 4 = 63.", "inline": []},
 "difficulty": 2, "source": "authored against the JAMB mathematics syllabus"}
```

### The borderline, decided

- **A fact about the subject** stays in the chapter. "$a^0 = 1$ needs a nonzero
  base" is true for every exam and every learner.
- **A fact about a paper** goes to the exam. "JAMB puts the synonym first as
  option A" is true of JAMB only, and WAEC does it differently.
- **A misconception** is written in the chapter, because it is about the
  subject. **A trap** is the same misconception with the exam's evidence
  attached, and lives with the exam.
- **A worked example** is teaching and stays in the chapter. **A past paper
  question with its examiner report** is an exam item and an exam task.
- **Mark allocation** belongs to the exam. **The reasoning behind the answer**
  belongs to the chapter.
- **Chapter exercises** are the source's own exercises, with the source's
  solutions, and they teach. **Recall checks** are ours, written in the
  exam's wording, and they drill. When a recall check is really a teaching
  exercise, it belongs in the chapter and the exam pack links to it.

### What a learner gets

The exam pack is the artefact a candidate actually uses, and it is assembled
per exam, subject and topic:

1. the chapter sections that teach the topic,
2. the exam's traps for that topic, with their paper evidence,
3. the exam's recall checks,
4. the exam's own past questions for the topic,
5. the marking schemes for the exam's theory tasks.

One route, one document, and the chapter is the teaching half of it:

```
GET /api/v1/exams/{exam}/subjects/{slug}/packs/{topic_slug}
```

### Migration from the current notes

| Today | Moves to |
| --- | --- |
| `topic_notes.examiner_traps` (31 traps) | `exam_trap`, with paper evidence attached |
| `topic_notes.active_recall_checks` (52 checks) | `exam_recall_check` |
| `topic_notes.exam`, `.subject`, `.topic_slug`, `.subtopic_slug` | `exam_syllabus_map` rows |
| `theory_questions` with marking methods and examiner reports (46, WAEC only) | `exam_task` |
| `blueprints` (81 rows, JAMB only) | `exam_paper_plan` |
| `questions` (3,870) | `exam_item`, each linked to the chapter section it teaches |

A trap without paper evidence is an opinion. It may stay as a chapter
misconception, but it does not become an exam trap until a past paper shows
it.

## Migration from exam-scoped notes

`topic_notes` stays in place while chapters are authored. Each production note
maps to one chapter section, and the note's `linked_question_ids` becomes the
chapter's `exam_links[].question_ids` in reverse.

| Old | New |
| --- | --- |
| `topic_notes.exam`, `.subject` | `exam_links[]` |
| `topic_notes.topic_slug`, `.subtopic_slug` | `exam_links[].topic_slug`, `.subtopic_slug` |
| `topic_notes.sections` | `sections[].teaching_text.blocks` |
| `topic_notes.worked_examples` | `sections[].worked_examples` |
| `topic_notes.active_recall_checks` | an exam-side revision pack, or chapter exercises |
| `topic_notes.examiner_traps` | an exam-side revision pack, not the chapter |
| `topic_notes.sources` | `sources[]` and per-object `provenance` |
| `topic_notes.linked_question_ids` | `exam_links[].question_ids` |

The notes routes are replaced in place by the chapter routes. v1 is still
being built and is expected to break while it takes shape, and only our own
app calls the API, so the break is ours to take. No client reads the notes
API today.
