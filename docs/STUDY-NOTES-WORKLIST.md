# Study Notes Worklist: Code Fixes and Content Gaps

**Snapshot:** commit `348a458` (tag `v0.0.2`), 9 November 2026.
**Status:** Open worklist. Close items as they land.
**Method:** Static read of the Rust source and a read-only query of the live Turso database. No cargo run on this device.
**Important:** The coverage numbers are a snapshot, not a permanent contract. Re-run the queries in section 4 after any import.

---

## 1. Code fixes for the developer

Ordered by risk. Each item names the location, the fix, and the test that proves it.

### Before the next import

- [ ] **C1. Measure the note after media resolution.**
  - Where: `src/store/catalog.rs:1592-1601` sizes the authored note. `src/api/v1/notes.rs:38-49` resolves media first and then sizes.
  - Problem: A note just under 16 KiB with relative image paths imports fine, then returns 500 at read.
  - Fix: Call `core::catalog::resolve_note` in `import_notes_from_json` and `seed_reference_notes` before the size check, or reject relative media in notes.
  - Test: Import a note just under the ceiling with one image, fetch it, expect 200.

- [ ] **C2. Apply one owner rule.**
  - Where: Import accepts a delegating board (`src/store/catalog.rs:1603-1656`). Reads require the note's own exam and subject to own the topic (`:1162-1167` and `:1208-1213`).
  - Problem: A NECO note on a WAEC-owned topic validates, stores, and is never served.
  - Fix: Normalize to `syllabus_owner` at import, or reject notes that do not own the placement. Use the same rule in both reads and `notes_index`.
  - Test: A NECO note on a WAEC topic is either stored as WAEC and served through NECO, or rejected with a clear error.

- [ ] **C3. Fail the command when the cloud push fails.**
  - Where: `src/main.rs:214` and `:271` discard `push_db`. `seed-reference-notes` never pushes (`:127-166`) and does not call `ensure_schema`.
  - Problem: The command prints success while the cloud is behind.
  - Fix: Propagate the push error and exit non-zero. Add `ensure_schema` and a push to the seed command, or print a clear local-only warning.
  - Test: Force a push failure, expect a non-zero exit and no success line.

- [ ] **C4. Reject duplicate ids and placements in one batch.**
  - Where: `src/store/catalog.rs:1697-1718` uses `INSERT OR REPLACE`. Unique placement indexes are at `src/store/schema.rs:52-53`. The function returns `notes.len()` at `:1722`.
  - Problem: Two notes with the same placement or id silently last-win, and the count overstates what landed.
  - Fix: Pre-scan the batch, reject duplicate ids and duplicate `(exam, subject, topic_slug, subtopic_slug)` pairs, and report inserted versus replaced rows.
  - Test: A file with two notes on the same placement fails before any write.

### Next

- [ ] **C5. Share one content validator between the test and the importer.**
  - Where: `authored_notes_files_are_valid_and_bounded` reads gitignored `data/notes` and returns early when absent (`src/api/v1/notes.rs:405-470`). The importer does not enforce the editorial rules.
  - Fix: Put the fixture under a tracked path and call one validator from both. Enforce 2 to 4 sections, exactly 2 recall checks, 4 options each, `correct_index` under 4, read time from 1 to 15, nonempty takeaway.
  - Test: A malformed note fails both the test and the import.

- [ ] **C6. Decide the anonymous syllabus contract.**
  - Where: `src/api/v1/public.rs:80-87` returns the same `Syllabus` model that carries `has_note` and `note_id` (`src/core/models/wire.rs:205-207` and `:219-221`).
  - Fix: Strip the fields for anonymous callers, or document them as public.
  - Test: Assert the chosen shape on `/api/v1/public/syllabus/...`.

- [ ] **C7. Make the content hash cover what it is used for.**
  - Where: `note_content_hash` (`src/store/catalog.rs:1683-1690`) hashes the body only.
  - Fix: Include title, read time, linked IDs, and placement, or rename and document it as body-only.
  - Test: Retitle a note and move it, expect a new hash if the hash is for change detection.

- [ ] **C8. Make import a sync, not an upsert.**
  - Where: All note writes are `INSERT OR REPLACE` (`src/store/catalog.rs:1539`, `:1561`, `:1698`).
  - Fix: Delete rows missing from the source, and preserve `created_at` on update.
  - Test: Import a file with one note removed, expect the row to disappear.

- [ ] **C9. Add a note ETag test.**
  - Where: The middleware exists (`src/api/middleware.rs:86-131`), but there is no note-specific 304 test.
  - Fix: Fetch a note, send `If-None-Match`, expect 304.
  - Test: One test per note endpoint.

- [ ] **C10. Update the study notes spec after C2 and C6.**
  - Where: `docs/STUDY-NOTES-SPEC.md` names old functions (`:234-235`) and documents the note fields only for the keyed syllabus (`:193-197`).
  - Fix: Align the schema, auth, function names, and public route with the code.

- [ ] **C11. Compute `has_full_paper` instead of storing and manually setting it.**
  - Where: `src/store/catalog.rs:2477` returns the stored `exams.has_full_paper` value. `src/api/v1/papers.rs:144-145` already derives `complete` from live subject stats and exam requirements.
  - Problem: A manual set can go stale as content is added or removed.
  - Fix: Derive `has_full_paper` at read time from subject readiness and the exam requirements, or remove the stored field from the response. Keep the existing country-scoped readiness endpoint as the source of truth, and define any-country versus all-country semantics for multi-country exams.
  - Test: Add verified questions that cross a readiness boundary and expect the exam completion value to flip without a direct database edit.

**Contract decision:** G5 covers `linked_question_ids`. The developer should settle that before the content team authors more notes.

---

## 2. Content gaps for the content owner

### Snapshot

| Item | Value |
|---|---:|
| Notes | 26 |
| Topic-level notes | 1 |
| Subtopic-level notes | 25 |
| Subject pairs with notes | 4 |
| Subject rows that can see notes | 5 |
| Topics covered | 14 of 1,461 |
| Subtopics covered | 25 of 5,488 |
| Placements that resolve | 26 of 26 |
| Notes meeting the 2 to 4 section and 2 recall standard | 25 of 26 |
| Notes with `linked_question_ids` | 0 of 26 |

Notes by subject:

| Exam | Subject | Notes | Topics covered | Subtopics covered |
|---|---|---:|---:|---:|
| JAMB | mathematics | 5 | 4 of 23 | 5 of 77 |
| JAMB | physics | 2 | 1 of 39 | 1 of 206 |
| JAMB | use-of-english | 12 | 3 of 3 | 12 of 12 |
| WAEC | english-language | 7 | 6 of 11 | 7 of 60 |

NECO English sees the 7 WAEC English notes through the shared syllabus. It is the only NECO subject row with visible notes. NECO has 27 subjects with no syllabus rows of their own, so they cannot host notes yet.

### Gaps and actions

- [ ] **G1. Fix or retire `note_phys_jamb_motion`.**
  It is the only topic-level note and the only note below the editorial standard: 2 sections, 0 worked examples, 1 recall check, 1 trap, 4 minutes. Either bring it to standard or mark it as a demo and remove it from the live table.

- [x] **G2. WAEC question bank (partially closed, 10 November 2026).**
  WAEC grew from 1 verified question to 1,227 verified questions (all with sourced explanations and human verification records), across 25 subjects: 19 core subjects at 50 each, english-language 60, marketing 50, office-practice 50, catering-craft 49, livestock-farming 41, book-keeping 27. Sources: myschool.ng classroom collections (2016 to 2025 pools), each question carries a citation with source item ID, source URL, and sourced explanation URL. Figures are content-addressed in the media repo. In progress: topping every subject up toward deeper pools (target 2,000 WAEC questions). Remaining zero-coverage WAEC subjects on myschool.ng: nigerian-history, foods-and-nutrition, physical-education, home-management, music, hausa, igbo, technical-drawing, visual-art, french, arabic. WAEC notes can now link questions for most subjects.

- [ ] **G3. Add questions for JAMB physics motion and projectiles.**
  JAMB physics has 105 questions, 102 verified, but both motion notes sit on subtopics with zero questions. Add questions to the two subtopics or link existing ones.

- [ ] **G4. Add questions for JAMB mathematics arithmetic progression.**
  JAMB mathematics has 60 questions, 59 verified, but the AP subtopic has zero. The note is live and cannot lead to practice.

- [ ] **G5. Reconsider `linked_question_ids` before authoring more notes.**
  - What it is: a JSON array of question IDs stored on each note, meant to name the questions to practise after reading. No handler reads it. All 26 notes have `[]`.
  - Why it is redundant: `questions.subtopic_id` already links questions to a subtopic, and the note already carries `subtopic_slug`. The list duplicates that relationship and goes stale when a question is deleted or re-imported with a new ID.
  - Storage is not the concern: 20 IDs per note is under 1 KB. The cost is curation and drift.

  | Option | Work | Risk | Choose when |
  |---|---|---|---|
  | Remove the field and derive related questions from `(exam, subject, subtopic_slug)` | Low | The note response loses a key | Default |
  | Keep the field and fill it automatically at import | Low | Still redundant, still can drift | Clients want the IDs inside the note payload |
  | Keep the field and curate it by hand | High | Stale IDs when questions change | Editorial selection or order matters |

  Recommended: remove it from the note contract. Resolve related questions in the store or a dedicated endpoint using the note's exam, subject, and subtopic. If the team keeps it, validate every ID on import, add it to the content hash, and test that a missing ID fails the import. Do not hand-populate it before this decision.

- [ ] **G6. Expand note coverage by demand.**
  Only 4 subject pairs have notes. High-volume JAMB subjects with zero notes:

  | Subject | Verified questions | Notes today |
  |---|---:|---:|
  | computer-studies | 189 | 0 |
  | biology | 112 | 0 |
  | government | 110 | 0 |
  | literature-in-english | 106 | 0 |
  | chemistry | 103 | 0 |
  | economics | 77 | 0 |

  Pick one batch and author notes for the topics those questions cover. JAMB use-of-english is already at 12 of 12 subtopics. The next highest return is a subject with verified questions and zero notes.

- [ ] **G7. Restore the authored note source.**
  No note JSON exists in git or on disk. The 26 rows live only in the database. Add a tracked source or an export command before authoring more, or the next editor has no file to change.

- [ ] **G8. Add the missing JAMB commerce blueprint.**
  JAMB has a full paper count for all 25 subjects, but only 24 subjects have blueprint rows. Commerce is the missing one, so it uses the count gate while the other subjects can report blueprint readiness.

---

## 3. Re-check commands

Run these after any import. They are read-only.

```sql
-- Notes by subject and level
SELECT exam, subject, count(*) AS notes,
       sum(CASE WHEN subtopic_slug IS NULL OR subtopic_slug='' THEN 1 ELSE 0 END) AS topic_level,
       sum(CASE WHEN subtopic_slug IS NOT NULL AND subtopic_slug<>'' THEN 1 ELSE 0 END) AS subtopic_level
FROM topic_notes GROUP BY exam, subject ORDER BY exam, subject;

-- Coverage against the full syllabus
WITH totals AS (
  SELECT t.exam, t.subject, count(DISTINCT t.slug) AS topics, count(st.slug) AS subtopics
  FROM topics t LEFT JOIN subtopics st ON st.topic = t.slug
  GROUP BY t.exam, t.subject
), covered AS (
  SELECT exam, subject,
         count(DISTINCT topic_slug) AS topics_cov,
         count(DISTINCT CASE WHEN subtopic_slug IS NOT NULL AND subtopic_slug<>''
                             THEN topic_slug||'/'||subtopic_slug END) AS subtopics_cov
  FROM topic_notes GROUP BY exam, subject
)
SELECT c.exam, c.subject, c.topics_cov, t.topics, c.subtopics_cov, t.subtopics
FROM covered c JOIN totals t ON t.exam=c.exam AND t.subject=c.subject;

-- Notes whose subtopic has no questions
SELECT n.exam, n.subject, n.id,
       (SELECT count(*) FROM questions q
        WHERE q.exam=n.exam AND q.subject=n.subject AND q.subtopic_id=n.subtopic_slug) AS q_in_subtopic
FROM topic_notes n
WHERE n.subtopic_slug IS NOT NULL AND n.subtopic_slug <> ''
ORDER BY q_in_subtopic, n.exam, n.subject;
```

---

## 4. Snapshot limit

These numbers come from commit `348a458` and the live database on 9 November 2026. They are not a permanent contract. Re-run the queries in section 3 after any import.

Question counts updated 10 November 2026: WAEC 1,227 verified (G2), JAMB 2,241 unchanged.
