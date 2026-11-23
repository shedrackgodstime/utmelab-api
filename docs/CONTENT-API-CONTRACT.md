# Content API contract

**Status: active replacement contract**

This is the contract between the external Content API and its clients. The
Content API owns reusable educational and exam content. It does not own
learners, study sessions, submitted answers, progress, scores, or
recommendations.

The contract is intentionally small:

```text
exam → subject → syllabus topic → lessons
exam question → syllabus topic
exam question ↔ lesson
question → passage
```

Lessons are exam-neutral. Syllabus topics and questions are exam-specific.

This contract is implemented by the current API. Notes and textbook routes are
removed; lessons are the teaching-content surface.

## 1. Rules

1. Responses are JSON and use `snake_case`.
2. Objects have stable IDs or stable identifying paths.
3. References use IDs or stable slugs; related objects are not recursively
   embedded.
4. Missing content is represented by an empty list or `null`; content is never
   invented.
5. The Content API does not return learner state.
6. A lesson must not contain `exam`, `year`, `paper`, `weight`, or other
   exam-specific fields.
7. A question may contain exam-specific fields.
8. A passage is a reusable stimulus and may be referenced by many questions.
9. Topic-to-lesson and lesson-to-question relationships are many-to-many.
10. A lesson ID is a stable conceptual identity; each published content change
    increments its `version`. Previous revisions remain recoverable and may be
    requested with `?version=N`.
11. Consumers receive only published lessons. Draft and retired lessons are
    authoring states, not normal catalog content.

## 2. Common types

### Rich text

```json
{
  "text": "Newton’s Second Law is written as F = ma.",
  "inline": []
}
```

`inline` contains formatting or media anchors. Offsets are Unicode scalar
offsets, not byte offsets.

### Reference

```json
{
  "id": "lesson:newtons-second-law",
  "title": "Newton’s Second Law"
}
```

The ID is authoritative. `title` is a display convenience.

### Provenance

```json
{
  "publisher": "OpenStax",
  "title": "College Physics 2e",
  "url": "https://example.org/source",
  "locator": "Section 4.2",
  "licence": "CC BY 4.0"
}
```

## 3. Exam catalogue

### Exam

```json
{
  "code": "JAMB",
  "name": "Joint Admissions and Matriculation Board",
  "status": "live"
}
```

### Subject

```json
{
  "exam": "JAMB",
  "slug": "physics",
  "name": "Physics",
  "is_compulsory": false
}
```

### Syllabus

```json
{
  "exam": "JAMB",
  "subject": "physics",
  "topics": [
    {
      "slug": "mechanics",
      "name": "Mechanics",
      "order": 1,
      "weight": null,
      "objectives": ["Explain the relationship between force and motion."],
      "subtopics": [],
      "lesson_refs": [
        {"id": "lesson:newtons-second-law", "title": "Newton’s Second Law"}
      ]
    }
  ]
}
```

`weight: null` means no verified syllabus weight is available; it does not
mean zero.

The topic is exam-owned. Its `lesson_refs` connect the syllabus topic to
exam-neutral lessons. One topic may reference many lessons, and one lesson may
be referenced by topics from many exams.

The replacement syllabus response may retain `subtopics` when the source
syllabus has them. It must remove the legacy `has_note` and `note_id` fields.
Subtopics may also carry `lesson_refs` when a lesson is placed more precisely
than the parent topic.
`question_count` and `summary` counts may remain as catalogue metadata, but
they do not represent learner progress.

## 4. Lesson

A lesson is the primary teaching unit. It teaches one coherent idea, skill, or
connected group of ideas.

The `id` remains stable for the same conceptual lesson. `version` changes when
the authored content changes. This avoids breaking bookmarks while preserving
the ability to identify the exact content version used by a client.

```json
{
  "id": "lesson:newtons-second-law",
  "version": 1,
  "status": "published",
  "title": "Newton’s Second Law",
  "description": {
    "text": "How net force, mass, and acceleration are related.",
    "inline": []
  },
  "subject": "physics",
  "level": "secondary",
  "estimated_minutes": 25,
  "objectives": [
    {
      "id": "objective:force-mass-acceleration",
      "statement": "Explain the relationship between force, mass, and acceleration.",
      "bloom_level": "understand"
    }
  ],
  "content": [
    {
      "id": "block:introduction",
      "type": "explanation",
      "body": {"text": "Newton’s Second Law describes how force changes motion.", "inline": []}
    },
    {
      "id": "block:formula",
      "type": "formula",
      "expression": "F = ma",
      "caption": {"text": "Force equals mass multiplied by acceleration.", "inline": []}
    },
    {
      "id": "block:worked-example",
      "type": "example",
      "prompt": {"text": "A 2 kg object accelerates at 3 m/s². Find the force.", "inline": []},
      "steps": ["F = ma", "F = 2 × 3", "F = 6 N"],
      "answer": {"text": "6 N", "inline": []}
    }
  ],
  "checks": [
    {
      "id": "check:force-increases-acceleration",
      "after_block_id": "block:formula",
      "objective_id": "objective:force-mass-acceleration",
      "type": "multiple_choice",
      "prompt": {"text": "What happens when net force increases while mass stays constant?", "inline": []},
      "options": [
        {"id": "a", "text": {"text": "Acceleration increases", "inline": []}},
        {"id": "b", "text": {"text": "Mass disappears", "inline": []}}
      ],
      "answer": {"option_id": "a"},
      "feedback": {"text": "For constant mass, increasing net force increases acceleration.", "inline": []},
      "hint": null
    }
  ],
  "misconceptions": [
    {
      "id": "misconception:mass-is-weight",
      "claim": {"text": "Mass and weight are the same thing.", "inline": []},
      "correction": {"text": "Mass measures inertia; weight is a gravitational force.", "inline": []}
    }
  ],
  "summary": [
    {"text": "Net force causes acceleration.", "inline": []},
    {"text": "Acceleration depends on force and mass.", "inline": []}
  ],
  "example_question_refs": [
    {"id": "question:jamb-2024-physics-001", "title": "..."}
  ],
  "provenance": {},
  "content_hash": "sha256:..."
}
```

Required lesson fields are `id`, `title`, `subject`, `content`, and
`provenance`. Objectives, checks, examples, misconceptions, summaries, and
question references may be empty when the source does not provide them.

Checks are lesson content. They are not exam questions and do not create a
learner attempt or score in the Content API.

## 5. Questions

A question is exam-owned assessment content. It is tagged to the syllabus
topic it belongs to and may reference the lesson that teaches the tested idea.

```json
{
  "id": "question:jamb-2024-physics-001",
  "exam": "JAMB",
  "subject": "physics",
  "year": 2024,
  "topic_slug": "mechanics",
  "source": "past_paper",
  "text": {"text": "Which expression gives the net force?", "inline": []},
  "options": [
    {"id": "a", "text": {"text": "F = ma", "inline": []}},
    {"id": "b", "text": {"text": "F = m/a", "inline": []}}
  ],
  "answer": "a",
  "lesson_refs": [
    {"id": "lesson:newtons-second-law", "title": "Newton’s Second Law"}
  ],
  "passage_id": null,
  "explanation": null,
  "marks": 1,
  "difficulty": 2
}
```

`answer` is an option ID, never an array index or display label. Questions may
reference more than one lesson when they genuinely assess multiple ideas.

The default question response withholds `answer` and `explanation`. They are
returned only when `include_explanation=true`. `passage` is returned only when
`include_passage=true`; `passage_id` remains available when the question has a
passage.

## 6. Passages

A passage is a reusable stimulus. Questions carry only `passage_id`; clients
resolve the passage separately or through an explicitly expanded response.

```json
{
  "id": "passage:jamb-english-2024-001",
  "exam": "JAMB",
  "subject": "use-of-english",
  "year": 2024,
  "kind": "comprehension",
  "title": null,
  "author": null,
  "text": {"text": "Passage text...", "inline": []}
}
```

## 7. Relationships

```text
syllabus topic → lesson_refs
lesson → example_question_refs
topic → questions
question → passage_id
```

Lessons reference only the questions they intentionally demonstrate. A topic
owns the complete question set; consumers should use topic-based question
filters for independent practice.

## 8. Endpoints

```text
GET /api/v1/exams
GET /api/v1/exams/{exam}/subjects
GET /api/v1/subjects/{exam}/{subject}/syllabus
GET /api/v1/topics/{exam}/{subject}/{topic_slug}

GET /api/v1/lessons/{lesson_id}

GET /api/v1/questions
GET /api/v1/questions/{question_id}

GET /api/v1/passages?ids={id1},{id2}
GET /api/v1/passages/{passage_id}
```

Useful question filters are `exam`, `subject`, `topic_slug`, and `year`.
Filtering changes only the result set, not the question shape.

The current API already supports `topic`, `subtopic`, `exam`, `subject`,
`year`, `source`, `verified`, `country`, paging, `include_explanation`, and
`include_passage`. The replacement may rename `topic` to `topic_slug`, but it
must not remove the existing filtering capability without a versioned change.

## 9. Implementation status

The Content API implements this contract:

1. `GET /api/v1/lessons/{lesson_id}` returns the latest published version, or a
   requested published version through `?version=`.
2. Syllabus topics and subtopics expose `lesson_refs`, while topic detail does
   the same for topic-level placements.
3. Note fields and note routes are absent from the replacement surface.
4. Question responses retain the existing exam,
   subject, year, source, subtopic, passage, verification, answer-withholding,
   and paging behavior.
5. Lesson-to-example-question and topic-to-lesson relationships are validated ID
   references; do not infer them from titles.
6. `site/openapi.json` is generated from the implemented routes and DTOs.

## 10. Out of scope

This contract does not include textbooks, chapters, sections, notes, learner
profiles, study plans, study sessions, submitted answers, attempts, scores,
mastery, streaks, recommendations, or client UI state.

The app may create a study session around a lesson, but that state stays in the
app and is never added to the lesson response.
