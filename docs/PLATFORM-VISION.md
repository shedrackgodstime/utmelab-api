# UTME-Lab platform vision

Status: Active
Last updated: 2026-11-12

This is the whole picture: what we are building, what owns what, what the
data looks like, what the API looks like, how content gets made, and the order
we build it in. It is the map. Individual specs (`docs/CONTENT-BOOK-SCHEMA.md`,
`docs/CONTENT-WORKFLOW-CONTRACT.md`) are the detail under it.

## 1. What we are building

A learning platform for the Nigerian senior secondary and tertiary entrance
examinations, built as two things that reference each other:

- **A textbook.** Complete, exam-independent teaching material. Books, chapters,
  sections, worked examples, exercises with full solutions. A learner can learn
  a topic from it with no exam in sight.
- **An exam layer.** For each exam (JAMB, WAEC, NECO): what that exam
  examines, how it weighs it, how its paper is written, what trips candidates
  up, and its own past questions and marking schemes.

The current product has only the first half, and it has the first half inside
the second: 26 study notes, each owned by an exam, covering 184 of 3,870
questions. This document describes how that becomes the real thing.

## 2. The learner

One person, two needs that pull in opposite directions:

- **I want to understand this.** A learner who has never heard of JAMB should
  be able to read a chapter on quadratic equations and come out able to solve
  one. That is the textbook.
- **I want to pass this exam.** The same learner wants to know which topics
  carry the most marks, how the paper is phrased, what the traps are, and to
  practise on real questions from real years. That is the exam layer.

The platform serves both, and never makes one serve the other. A textbook
chapter does not know which exam tests it. An exam does not teach.

## 3. The three layers and who owns what

```
                    ┌──────────────────────────────────────────────┐
                    │  TEXTBOOK  (owns the teaching)                │
                    │  books ── chapters ── sections ── exercises   │
                    └───────────────┬──────────────────────────────┘
                                    │  referenced by
                    ┌───────────────▼──────────────────────────────┐
                    │  EXAM LAYER  (owns the testing)              │
                    │  syllabus map, traps, recall checks, tasks,   │
                    │  paper plan                                   │
                    └───────────────┬──────────────────────────────┘
                                    │  contains
                    ┌───────────────▼──────────────────────────────┐
                    │  BANK  (owns the paper items)                 │
                    │  questions (exam items), passages, novels     │
                    └──────────────────────────────────────────────┘
```

Ownership rules, in one line each:

| Layer | Owns | Never owns |
| --- | --- | --- |
| Textbook | teaching text, worked examples, exercises, solutions, learning objectives, misconceptions about the subject | exam names, marks, paper style, past paper references |
| Exam layer | syllabus map, weights, traps with paper evidence, recall checks in exam wording, theory tasks with mark schemes, paper plan | teaching text, subject explanations |
| Bank | questions with their year, paper and number, explanations, passages, novels | chapter structure, exam weights |

References point one way. The bank links to a chapter section so a question
can say what it teaches. The exam layer links to a chapter section so a trap
can say what it is about. A chapter never links outward.

## 4. The data model

### Textbook tables (new)

| Table | Holds |
| --- | --- |
| `books` | id, title, subject_area, level, edition, licence, created_at, updated_at |
| `chapters` | id, book_id, order, title, learning_objectives, est_minutes, content_hash, timestamps |
| `chapter_sections` | id, chapter_id, order, slug, title, learning_objectives, teaching_text, worked_examples, misconceptions, summary_points, est_minutes, content_hash |
| `chapter_exercises` | id, section_id, kind, difficulty, marks, stem, options, answer, answer_kind, solution, tags, provenance |

### Exam tables (new)

| Table | Holds |
| --- | --- |
| `exam_syllabus_map` | exam, subject, topic_slug, subtopic_slug, chapter_section_id, weight_pct, expected_count, syllabus_version, source_locator, status |
| `exam_traps` | id, exam, subject, topic_slug, subtopic_slug, chapter_section_id, misconception, correction, signal, paper_evidence, frequency |
| `exam_recall_checks` | id, exam, subject, chapter_section_id, stem, options, answer, explanation, difficulty, source |
| `exam_paper_plans` | the current `blueprints` shape plus chapter_section_id |

### Tables that change shape

| Table | Today | Becomes |
| --- | --- | --- |
| `questions` | exam items with no teaching link | exam items plus `chapter_section_id`, so a question says what it teaches |
| `theory_questions` | 46 WAEC tasks with mark schemes | `exam_tasks` plus `chapter_section_id` |
| `subjects`, `topics`, `subtopics` | exam-scoped syllabus catalogue | unchanged. This is the exam's own catalogue and stays exactly as it is |
| `verifications` | human review of answers and explanations | unchanged, plus review of exercises and traps |

### Tables that retire

| Table | Becomes |
| --- | --- |
| `topic_notes` | chapter sections. The 26 notes become 26 sections across a handful of books |

The taxonomy is not deleted. `subjects`, `topics` and `subtopics` are the exam's
own catalogue of 105 (exam, subject) pairs, 1,461 topics and 5,488 subtopics.
That stays as the syllabus layer. What changes is that content stops living
there.

## 5. The API

v1 is still being built, so this is a reshape in place, not a new version.
Only our own app consumes it, and breakage is expected and acceptable.

### Textbook

```
GET /api/v1/textbooks                                   list books
GET /api/v1/textbooks/{book_id}                         book with its chapters
GET /api/v1/textbooks/{book_id}/chapters                chapters of a book
GET /api/v1/chapters/{chapter_id}                       chapter, with sections
GET /api/v1/chapters/{chapter_id}/sections/{section_id} one section, teaching text and examples
GET /api/v1/chapters/{chapter_id}/exercises             exercises with answers and solutions
GET /api/v1/sections/{section_id}/exercises             exercises of one section
```

### Exam

```
GET /api/v1/exams                                      exams and their coverage
GET /api/v1/exams/{exam}/subjects/{slug}/syllabus      the syllabus map: chapters, weights, counts
GET /api/v1/exams/{exam}/subjects/{slug}/packs/{topic}  the exam pack for a topic
GET /api/v1/exams/{exam}/subjects/{slug}/traps         traps with paper evidence
GET /api/v1/exams/{exam}/subjects/{slug}/recall        recall checks in exam wording
GET /api/v1/exams/{exam}/subjects/{slug}/theory        theory tasks with mark schemes
GET /api/v1/exams/{exam}/papers                        readiness and paper plan
```

### Bank (existing, extended)

```
GET /api/v1/questions            existing, plus include_explanation and the chapter link
GET /api/v1/questions/{id}       existing, plus the chapter section it teaches
GET /api/v1/passages             existing
GET /api/v1/novels               existing
```

### Retiring

`GET /api/v1/notes/{exam}/{subject}/{topic_slug}` and
`GET /api/v1/notes/subtopic/...` go away as the chapters that replace them
land. The chapter routes serve the same content in a better shape: a topic
route today returns one note with no exercises; a chapter section returns the
teaching, the examples, the exercises and the solutions, and the exam pack
adds the traps and the past questions.

## 6. How content gets made

```
  source (book, paper, syllabus)
        │
        ▼
  concept document ......... data/concepts/*.json, schema v4, one per idea,
        │                   provenance and deep context, no exam in sight
        ▼
  chapter .................. data/chapters/*.json, exam independent
        │                   validate_chapters.py must report 0 errors
        ▼
  exam artefacts ........... traps, recall checks, tasks, syllabus map,
        │                   each citing a chapter section and its paper evidence
        ▼
  import ................... staged through the ingestion manifest, then a
                            write to the replica and a push to Turso
```

Two pipelines, one rule: the chapter pipeline never mentions an exam, and the
exam pipeline never explains the subject.

Grounding rules stay as they are in `docs/CONTENT-WORKFLOW-CONTRACT.md`: no
invention, provenance on everything, honest licences, validation before
import.

### The scale of the work

54 distinct subject slugs across three exams. A textbook per subject area,
each with perhaps 10 to 30 chapters, puts the finish line at roughly 250 to
400 chapters. One chapter at a time is a hobby, not a build. The pipeline has
to carry the load, with human review concentrated where it matters: on the
exam side, where a mistake is a false claim about a paper.

## 7. The learner's journey

1. **Choose an exam, or do not.** A learner can browse the textbook with no
   exam at all.
2. **See the shape of the exam.** The syllabus map shows which chapters cover
   the exam's topics, with weights and expected question counts.
3. **Learn.** Read the chapter: sections, worked examples, misconceptions,
   summary points. Do the exercises, check the solutions.
4. **Learn the exam's habits.** The traps, each with the past paper that
   shows it. The recall checks, in the wording the exam uses.
5. **Practise.** The exam's own past questions for the topic, with
   explanations.
6. **Sit it.** An assembled paper, scored, with the mark scheme for the
   theory questions.

Steps 3 and 4 come from different halves of the platform, and the app shows
them in one place, per topic.

## 8. What we build, in order

| Phase | Work | Gate |
| --- | --- | --- |
| A | The chapter model and the validator, pilot complete | `validate_chapters.py` clean, pilot read end to end |
| B | One subject finished: every chapter and section for Mathematics, with exercises | coverage report shows no `thin` chapter |
| C | The exam side for that subject: syllabus map, traps with paper evidence, recall checks, theory tasks | every trap cites a paper |
| D | The API reshape in place: textbook routes, exam routes, packs. The app consumes them | the app runs on the new routes end to end |
| E | The question bank gains `chapter_section_id`; past questions link to the section they teach | every question resolves to a section or is marked orphan |
| F | Scale: the remaining subject areas, then NECO | coverage reports per book and per exam |
| G | `topic_notes` retired, `notes` routes removed | no chapter still points at a note |

Phase A is done. Phase B is the next real piece of work.

## 9. Levels: secondary and foundation

The main audience is senior secondary. The platform should also serve the
tertiary audience, because a student who enters university with a weak
foundation in mathematics, English or accounting is the same learner a year
later.

We already hold the material. 211 of the 529 concepts in the corpus are
university level:

| Source | Concepts | Level |
| --- | --- | --- |
| University Physics (OpenStax) | 93 | university |
| College Algebra (OpenStax) | 27 | university bridge |
| Contemporary Mathematics (OpenStax) | 20 | Nigerian university general mathematics |
| Calculus Volume 1 (OpenStax) | 7 | university |
| GST 101 and GST 102 Use of English (National Open University of Nigeria) | 40 | Nigerian university course |
| Spoken English: Phonetics and Phonology | 4 | tertiary ELT |
| Communication Essentials for College | 3 | tertiary ELT |
| Writing for Success | 2 | tertiary ELT |
| BBA1003 and BCOM1003 Principles of Financial Accounting | 4 | Nigerian university course |
| ACC 308 Public Sector Accounting | 2 | Nigerian university course |
| Statistics, Prealgebra, Algebra and Trigonometry, Entrepreneurship, World Regional Geography | 11 | university |

### Two tracks

| Track | Audience | Exam layer | Textbook |
| --- | --- | --- | --- |
| Secondary | senior secondary candidates | JAMB, WAEC, NECO | one book per subject area |
| Foundation | university entrants and students | none | one foundation book per subject area where it pays |

A book carries a level. A chapter may override it, so a secondary book can
hold the advanced chapters that bridge into the first year of university
without a second book for every subject area.

The foundation books that pay, in order of audience size: Mathematics
(Contemporary Mathematics plus College Algebra, Calculus and Statistics),
English Language (GST 101 and GST 102), Physics (University Physics),
Accounting (BBA1003 and ACC 308), Economics, Chemistry, Biology, Computer
Studies.

### The course layer

Tertiary content has no exam, so the exam layer does not apply to it. It has
a smaller sibling, the course layer:

- `course_syllabus_map`: course code, course title, institution, level, the
  chapter sections it uses, and the module structure where the course has one
  (GST 101 is organised as M1U1 to M1U5, and our concepts are already keyed
  to that structure).
- No traps, no past papers, no paper plan. A course is a map, not an exam.

This is the cleanest test of the architecture. If a university student will
pay for the textbook alone, with no exam layer at all, then the textbook is
genuinely good. That is a harder standard than anything the exam layer can
give us.

### The gaps for the foundation track

- Concepts carry no level today. Adding a `level` field to the concept schema
  is the first change.
- No tertiary practice bank. All 3,870 questions are secondary level. The
  chapter exercises are the practice, and they come from the sources with
  their solutions, so the track works, but there is no Nigerian tertiary
  question bank to add later.
- No course map exists yet. One table and one authoring pass.

## 10. Sourcing

We take what we can get our hands on. The licence is not a gate we plan
around; the gate is whether the source is a textbook we can actually serve:
structured, illustrated where the subject needs it, explained, and reachable
without a PDF.

OpenStax is the spine, for three reasons.

- It is CNXML, not PDF. The text, the mathematics, the figures, the examples
  and the solutions are all separate, addressable objects. That is what lets
  a chapter carry a figure with its caption and alt text, and an exercise
  with a worked solution.
- The catalogue is wide enough to finish the platform: mathematics, physics,
  chemistry, biology, economics, accounting, business, sociology, psychology,
  political science, statistics and more, from pre-algebra to calculus, from
  College Physics to University Physics, from Biology 2e to Concepts of
  Biology.
- The pipeline is already ours. `scripts/scrape_openstax_cnx.py` turns a
  module into a concept document with its figures on disk, and
  `scripts/scrape_openstax_solutions.py` turns the solutions into steps.

One College Physics 2e is 34 chapters and 318 modules. The whole catalogue is
several hundred books. The 250 to 400 chapters the platform needs are inside
it, and the Foundation track is inside it too, because the same catalogue
runs from College Algebra through to Calculus Volume 3.

Other sources stay in the mix where they are better: the National Open
University of Nigeria for GST 101 and GST 102, Contemporary Mathematics for
the Nigerian general mathematics course, and the Nigerian tertiary accounting
courses. They are already in the corpus.

### What we show about a paper

Most of the questions in the bank are `claimed_paper`: self-published claims
of a past paper rather than confirmed official ones. We show them, and we
label them. Every paper in a pack carries its year and its provenance, and
the pack says how many of its papers are claims.

The reasoning: a candidate practising on a claimed paper is better informed
than a candidate practising on nothing, as long as nobody tells them the
paper is official. A confirmed paper always wins the label, and the label is
never dropped.

## 11. The rules that keep it honest

- **No invention.** Every fact, figure, example and answer traces to a source
  with a locator.
- **A trap needs evidence.** A misconception without a past paper behind it is
  an opinion, and it stays a chapter misconception.
- **One direction of reference.** Exam to chapter, never back.
- **Coverage is reported, not assumed.** Which chapters exist, which have
  exercises, which exam topics map to a chapter, which traps have evidence.
  The numbers go in the audits, not in a feeling.
- **The learner is the test.** A chapter that only makes sense to someone who
  already knows the topic is not finished.

## 12. Decisions still open

1. **Traps.** We have 3,706 claimed-paper questions with years and paper
   numbers. Do we mine them for the trap evidence, or do we write traps from
   the examiner reports first and attach evidence later?
2. **Foundation pilot.** Mathematics first (Contemporary Mathematics, the
   largest audience and the sources are already here), or Use of English for
   Tertiary first (40 concepts, already organised by module, so the course map
   is nearly written)?
