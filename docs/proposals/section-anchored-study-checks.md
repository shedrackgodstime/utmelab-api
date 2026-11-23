# Proposal: section-anchored formative study checks

**Status:** Implemented in the API; source authoring remains pending

**Raised from:** UtmeLab guided-study implementation

**Date:** 2026-11-20

## Summary

Expose short, source-backed formative checks as part of textbook teaching
content, anchored to a stable section and, where available, a learning
objective or position in the section. These checks support the familiar
lesson loop of explanation, worked example, learner attempt, and feedback.

They are not exam-paper questions or a standalone practice session. The
study engine should be able to prepare and cache a lesson, including its
checks, without choosing questions from an exam bank.

## Current observed contract

The textbook section endpoint
`GET /api/v1/chapters/{chapter_id}/sections/{section_id}` returns ordered
teaching blocks, objectives, worked examples, misconceptions, summary points,
exercise IDs, exam links, provenance, and a schema version. It does not
currently return a distinct collection of short formative checks anchored to
the teaching flow.

There are related but non-equivalent API records:

- `/api/v1/exam-practice` returns `ExamRecallCheck` items written in an exam's
  own wording. These belong to exam-practice use cases.
- `TopicNote.active_recall_checks` represents learning checks, but they are
  attached to the legacy topic-note model and are not section-anchored
  textbook teaching content.
- Textbook exercises provide problem/answer/solution material, but the
  contract does not identify a subset as short formative checks positioned
  within a lesson.

Clients should not have to infer that these records are interchangeable based
on their field shapes.

## Implemented contract

Add an optional, backward-compatible collection to section detail, or expose
an equivalent section-scoped resource. Illustrative shape:

```json
{
  "study_checks": [
    {
      "id": "stable-check-id",
      "order": 1,
      "position_after_block_id": "stable-content-block-id",
      "objective_id": null,
      "kind": "multiple_choice",
      "prompt": {},
      "options": [
        { "id": "a", "content": {} },
        { "id": "b", "content": {} }
      ],
      "answer": { "option_id": "a" },
      "feedback": {},
      "hint": null,
      "provenance": {}
    }
  ]
}
```

The response field is omitted when a section has no checks. The current typed
response kind is `multiple_choice`; new response kinds require a separate
consumer and API implementation. Checks are stored with their owning section,
validated before serving, and included in that section's content hash. The
opaque content hash is returned as a section revision token for client cache
comparison.

- Each check has a stable ID and an explicit owning section. It may refer to a
  stable content block or objective when the source provides that relation.
- The response can preserve authored order and placement in the teaching
  sequence. It must not depend on clients matching titles or guessing where a
  check belongs.
- The schema does not embed session timing, paper assembly, score targets, or
  question-bank draw rules.
- Correct answers and explanatory feedback are available to the lesson
  renderer, but the client must withhold them until after the learner attempts
  or explicitly reveals the answer. The API should document that disclosure
  behavior.
- Provenance and content versioning follow the relevant section/check source.
  Changes to a check are detectable for local refresh and audit.
- Empty or absent checks mean “none supplied,” not an invitation to fabricate
  or infer from a question count.
- Existing section fields and clients remain compatible. The design should
  avoid duplicating full exercise payloads; when an existing authored
  exercise is intentionally used as a study check, represent an explicit
  stable reference and usage capability.

The API exposes checks inline on section detail and stores them in the
section's `study_checks` JSON column. The response distinguishes them from
exam recall checks and chapter exercises.

No real Physics check has been authored by this implementation. The API tests
use synthetic checks only; absent source-authored checks remain absent.

## Acceptance criteria

- A client can request a textbook section and determine whether it includes
  lesson-embedded checks without consulting the exam question bank.
- Every returned check has an unambiguous section association and stable
  identity; optional placement/objective links are explicit.
- A client can render feedback only after a learner response while preserving
  the source-authored answer and explanation.
- Exam-worded recall checks and lesson-embedded formative checks remain
  distinguishable in OpenAPI and documentation.
- A content update to a check can invalidate the relevant local section
  activity without resetting learner progress.
- Empty-check, malformed-check, and backward-compatible section responses
  have API tests.

## Non-goals

- This proposal does not add a question-bank endpoint, exam paper, timed
  session, or standalone practice engine.
- It does not require every section to have a check or prescribe a question
  count.
- It does not ask the API to choose a learner's next activity, schedule
  review, store learner attempts, or own learner progress.
- It does not require clients to use active recall checks from legacy notes.
- It does not prescribe a session length or force one pedagogical pattern on
  every subject.
