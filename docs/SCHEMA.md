# UTME-Lab schema

Status: Active
Last updated: 2026-11-12

One schema. Every surface is a projection of it: the document we author, the
row we store, the JSON we serve, the object the app renders. When a shape
changes, it changes once, here.

## 1. Where we are

Production holds 27 tables. They came from three sources that never met:

| Origin | Tables | Shape |
| --- | --- | --- |
| The API itself | `api_keys`, `api_access_tokens`, `dashboard_users`, `sessions`, `reports`, `meta`, `api_schema_migrations` | platform, fine as it is |
| The exam catalogue | `exams`, `countries`, `exam_requirements`, `subjects`, `topics`, `subtopics`, `topic_countries` | the exam's own syllabus layer, fine as it is |
| The content bank | `questions`, `passages`, `topic_notes`, `theory_questions`, `novels`, `novel_chapters`, `novel_characters`, `novel_themes`, `novel_questions`, `blueprints`, `verifications` | the old content model, exam scoped |

And three document schemas on the authoring side, which also do not meet:

| Document | Version | Used for |
| --- | --- | --- |
| `data/concepts/*.json` | 4 | source derived material, staged, never shipped |
| `topic_notes` rows and their API model | no version | the exam scoped notes in production |
| `data/chapters/*.json` | 1 | the new textbook chapters |

The content shape is `docs/CONTENT-BOOK-SCHEMA.md`. The chapters are that
shape in storage. Everything else adapts to them.

## 2. The layers

```
  source layer      concepts, staging only, never served
        │
        ▼
  textbook layer    books > chapters > sections > exercises, with figures
        ▲
        │  exam references chapter
        │
  exam layer        syllabus map, traps, recall checks, tasks, paper plan
        ▲
        │  exam owns the paper
        │
  bank layer        questions, theory questions, passages, novels
        ▲
        │  the platform owns access
        │
  platform layer    keys, tokens, sessions, reports, reviews
```

References point one way, downwards. The textbook layer names no exam. The
exam layer names chapters and its own items. The bank belongs to an exam and
may name the chapter section it teaches. The platform layer owns access and
review, and knows nothing about content.

## 3. The textbook layer, canonical

The chapter document is the shape. These tables are its storage.

```sql
CREATE TABLE IF NOT EXISTS books (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  subject_area TEXT NOT NULL,
  level TEXT NOT NULL,
  edition TEXT NOT NULL DEFAULT 'draft-1',
  licence TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chapters (
  id TEXT PRIMARY KEY,
  book_id TEXT NOT NULL,
  order_index INTEGER NOT NULL,
  title TEXT NOT NULL,
  learning_objectives TEXT NOT NULL DEFAULT '[]',
  est_minutes INTEGER NOT NULL DEFAULT 0,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chapter_sections (
  id TEXT PRIMARY KEY,
  chapter_id TEXT NOT NULL,
  order_index INTEGER NOT NULL,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  learning_objectives TEXT NOT NULL DEFAULT '[]',
  teaching_text TEXT NOT NULL DEFAULT '{"blocks":[]}',
  worked_examples TEXT NOT NULL DEFAULT '[]',
  misconceptions TEXT NOT NULL DEFAULT '[]',
  summary_points TEXT NOT NULL DEFAULT '[]',
  no_worked_example_reason TEXT,
  est_minutes INTEGER NOT NULL DEFAULT 0,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chapter_exercises (
  id TEXT PRIMARY KEY,
  section_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  difficulty INTEGER NOT NULL,
  marks REAL NOT NULL,
  stem TEXT NOT NULL,
  options TEXT NOT NULL DEFAULT '[]',
  answer TEXT NOT NULL,
  answer_kind TEXT NOT NULL,
  solution TEXT NOT NULL DEFAULT '[]',
  tags TEXT NOT NULL DEFAULT '[]',
  answer_note TEXT,
  provenance TEXT NOT NULL,
  solution_provenance TEXT NOT NULL DEFAULT '',
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chapter_figures (
  id TEXT PRIMARY KEY,
  section_id TEXT NOT NULL,
  order_index INTEGER NOT NULL,
  asset_url TEXT NOT NULL,
  caption TEXT NOT NULL,
  alt TEXT NOT NULL,
  licence TEXT NOT NULL DEFAULT '',
  content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapter_sources (
  chapter_id TEXT NOT NULL,
  publisher TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  locator TEXT NOT NULL,
  licence TEXT NOT NULL,
  PRIMARY KEY (chapter_id, publisher, title, locator)
);
```

### The same shape in three places

A section is one object. Here it is as a document, as a row and as JSON:

```jsonc
// document, data/chapters/phy_forces_and_newtons_laws.json
{
  "id": "sec-2",
  "order": 2,
  "title": "The force concept and the free-body diagram",
  "est_minutes": 20,
  "teaching_text": {"blocks": [...]},
  "worked_examples": [...],
  "misconceptions": [...],
  "summary_points": [...],
  "practice_exercise_ids": ["ex-sec-2-01", "ex-sec-2-02"],
  "provenance": {...}
}
```

```sql
-- row
chapter_sections(id, chapter_id, order_index, slug, title, learning_objectives,
                 teaching_text, worked_examples, misconceptions, summary_points,
                 no_worked_example_reason, est_minutes, content_hash, ...)
```

```jsonc
// API response
{
  "id": "sec-2",
  "chapter_id": "phy_forces_and_newtons_laws",
  "order": 2,
  "title": "The force concept and the free-body diagram",
  "est_minutes": 20,
  "teaching_text": {"blocks": [...]},
  "worked_examples": [...],
  "misconceptions": [...],
  "summary_points": [...],
  "exercises": [...],
  "provenance": {...}
}
```

The document is the author facing view, the row is storage, the response is
the read view with the exercises inlined. One shape, three views.

## 4. The exam layer, canonical

Same shape as the textbook layer, with the exam on it.

```sql
CREATE TABLE IF NOT EXISTS exam_syllabus_map (
  exam TEXT NOT NULL,
  subject TEXT NOT NULL,
  topic_slug TEXT,
  subtopic_slug TEXT,
  chapter_id TEXT NOT NULL,
  chapter_section_id TEXT NOT NULL,
  weight_pct REAL,
  expected_count REAL,
  syllabus_version TEXT,
  source_locator TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'covered',
  content_hash TEXT NOT NULL,
  PRIMARY KEY (exam, subject, topic_slug, subtopic_slug, chapter_section_id)
);

CREATE TABLE IF NOT EXISTS exam_traps (
  id TEXT PRIMARY KEY,
  exam TEXT NOT NULL,
  subject TEXT NOT NULL,
  topic_slug TEXT,
  subtopic_slug TEXT,
  chapter_section_id TEXT NOT NULL,
  misconception TEXT NOT NULL,
  correction TEXT NOT NULL,
  signal TEXT,
  paper_evidence TEXT,
  frequency TEXT,
  provenance TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exam_recall_checks (
  id TEXT PRIMARY KEY,
  exam TEXT NOT NULL,
  subject TEXT NOT NULL,
  chapter_section_id TEXT NOT NULL,
  stem TEXT NOT NULL,
  options TEXT NOT NULL DEFAULT '[]',
  answer TEXT NOT NULL,
  explanation TEXT NOT NULL,
  difficulty INTEGER NOT NULL DEFAULT 2,
  source TEXT NOT NULL DEFAULT '',
  content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exam_paper_plans (
  id TEXT PRIMARY KEY,
  exam TEXT NOT NULL,
  subject TEXT NOT NULL,
  chapter_section_id TEXT,
  topic_slug TEXT NOT NULL,
  section TEXT,
  members TEXT NOT NULL DEFAULT '[]',
  paper_size INTEGER,
  pct REAL,
  pct_low REAL,
  pct_high REAL,
  expected REAL,
  expected_low REAL,
  expected_high REAL,
  source TEXT,
  method TEXT,
  confidence TEXT,
  status TEXT,
  note TEXT,
  content_hash TEXT NOT NULL
);
```

`exam_paper_plans` is `blueprints` with a chapter link. `exam_traps` and
`exam_recall_checks` are the pieces that used to sit inside `topic_notes`.

## 5. The bank layer, canonical

The bank is the paper items. It gains one column and loses nothing.

```sql
-- questions gains:
  chapter_section_id TEXT          -- the section this question teaches

-- theory_questions becomes exam_tasks:
  id, exam, subject, year, paper, section, question_number,
  topic_slug, subtopic_slug, chapter_section_id,
  total_marks, stem, diagram_url, sub_parts, formulation_bridge,
  marking_methods, diagram_rubric, penalties, examiner_report,
  content_hash, created_at, updated_at
```

A question belongs to an exam and may teach a chapter section. The chapter
never names the question.

## 6. The platform layer, canonical

Two changes.

**Review becomes general.** Today `verifications` can only review a question,
with `question_id` as the target. Under one schema, review applies to any
content object: a section, an exercise, a trap.

```sql
CREATE TABLE IF NOT EXISTS content_reviews (
  id TEXT PRIMARY KEY,
  target_type TEXT NOT NULL,      -- question | exercise | section | trap | task
  target_id TEXT NOT NULL,
  kind TEXT NOT NULL,             -- human | model | import
  verdict TEXT NOT NULL,          -- pass | fail | pending
  scope TEXT NOT NULL,            -- which parts were checked
  verifier TEXT NOT NULL,
  detail TEXT,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

The 3,837 existing question reviews become rows in `content_reviews`, and the
same mechanism reaches exercises and traps.

**Content hash is everywhere.** Every content row carries the hash of the
document it came from, so a change is detectable and a stale copy is
findable.

## 7. The invariants

The same checks, wherever the shape appears. The validator runs them on the
document, the API runs them on write, and the database holds what passed.

1. A chapter names no exam. An exam may name a chapter.
2. Every content object carries provenance with a publisher, a title, a
   locator and a licence.
3. Every exercise has an answer, an answer kind, and a solution with at least
   one step.
4. Every section has learning objectives, at least two summary points, and a
   worked example or a reason for having none.
5. Every figure has an asset, a caption and alt text.
6. Every exercise belongs to exactly one section, and that section lists it.
7. An exam link without a topic is only honest when the exam's catalogue for
   that subject does not exist yet, and then it says so.
8. A trap without paper evidence is a chapter misconception, not a trap.

## 8. Migration map

| Today | Becomes | Action |
| --- | --- | --- |
| `topic_notes` | `chapters`, `chapter_sections`, `chapter_exercises` | retire after the chapters that replace it land |
| `blueprints` | `exam_paper_plans` | copy, add `chapter_section_id` |
| `theory_questions` | `exam_tasks` | rename, add `chapter_section_id` |
| `questions` | unchanged | add `chapter_section_id` |
| `verifications` | `content_reviews` | copy with `target_type = 'question'` |
| `subjects`, `topics`, `subtopics` | unchanged | the exam's catalogue, it stays |
| `exams`, `countries`, `exam_requirements` | unchanged | they stay |
| `passages`, `novels` and their children | unchanged | they stay, for now |
| `api_keys`, `api_access_tokens`, `dashboard_users`, `sessions`, `reports` | unchanged | they stay |
| `meta`, `api_schema_migrations` | unchanged | they stay |

## 9. The order

1. The new tables, as migrations, alongside the old ones. Nothing breaks.
2. Import the chapters that exist, into the new tables.
3. Serve the new routes from the new tables, and the app moves over.
4. The notes routes go, and `topic_notes` goes.
5. The bank gains `chapter_section_id`, and the exam layer gains its rows.
6. `verifications` becomes `content_reviews`.

Every step is additive until the last one, and the last one has nothing left
pointing at it.
