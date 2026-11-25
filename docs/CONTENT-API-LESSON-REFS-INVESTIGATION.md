# Investigation: Empty `lesson_refs` on syllabus topics

## Symptoms

The UtmeLab client showed "Coming soon" for every syllabus topic on JAMB Use of
English and WAEC English Language. The API served published lessons and verified
questions, but the syllabus response held no `lesson_refs`.

Direct lesson reads worked. Authenticated syllabus reads returned HTTP 200 with
empty refs for `JAMB / use-of-english`, `WAEC / english-language`, and several
other subjects.

## Cause

The lesson importer wrote `topic_links` into JSON `lesson_refs` on the `topics`
and `subtopics` rows. The syllabus handler read a separate `topic_lessons`
table. That table had no matching rows on the serving replica. The two writers
and readers were looking at different stores.

The extra table also broke the intended ownership rule. Lessons are exam
neutral. The exam-owned syllabus topic should hold the relationship. Adding a
second relationship table made the model harder to maintain without adding a
capability the topic row did not already have.

## Resolution

The API now uses the JSON refs as the single source of truth.

- `import_bundle()` inserts refs at the authored `order_index` position in the
  target topic or subtopic row. Array position is the curriculum order, and
  `ContentReference.order` mirrors it.
- `build_syllabus()` reads those JSON refs for the syllabus owner. JAMB and
  WAEC topics can both point at the same exam-neutral lesson.
- `get_topic()` uses the same visible refs, so topic detail and syllabus cannot
  disagree.
- Only published lessons are served, and each served title is the current
  lesson title.
- Subtopic rows are keyed by topic slug only. If two exams own one topic slug,
  subtopic ref reads and writes fail closed instead of serving one exam's refs
  to another.
- Schema migration 17 keeps existing JSON refs and copies legacy rows in
  authored order when the JSON array is empty. Migration 19 folds remaining
  `topic_lessons` rows into the JSON refs, skips shared subtopic rows with more
  than one syllabus owner, drops the table, and removes it from the declared
  shapes. Fresh databases no longer create it.
- Schema migration 20 renumbers stored refs from their array position, so a
  replica upgraded through schema 18 publishes the same order contract.

## Verification

Automated coverage checks import to syllabus, import to topic detail, order,
authored position insertion, idempotent reimport, draft filtering, JAMB and
WAEC reuse, partial bundle preservation, ambiguous topic owners, fresh schema
shape, migration backfill, a real legacy upgrade, and order normalization.

Deployment still needs live proof on `api.jambmax.com` for both syllabus
endpoints before any production claim is made.
