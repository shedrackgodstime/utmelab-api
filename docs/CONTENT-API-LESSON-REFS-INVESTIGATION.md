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

- `import_bundle()` writes ordered refs into the target topic or subtopic row.
  Array position is the curriculum order, and `ContentReference.order` mirrors
  it.
- `build_syllabus()` reads those JSON refs for the syllabus owner. JAMB and
  WAEC topics can both point at the same exam-neutral lesson.
- `get_topic()` uses the same visible refs, so topic detail and syllabus cannot
  disagree.
- Only published lessons are served, and each served title is the current
  lesson title.
- Schema migration 19 folds any remaining `topic_lessons` rows into the JSON
  refs, drops the table, and removes it from the declared shapes. Fresh
  databases no longer create it.

## Verification

Automated coverage checks import to syllabus, import to topic detail, order,
idempotent reimport, draft filtering, JAMB and WAEC reuse, fresh schema shape,
and migration backfill.

Deployment still needs live proof on `api.jambmax.com` for both syllabus
endpoints before any production claim is made.
