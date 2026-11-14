//! The textbook layer: books, chapters, sections and exercises.
//!
//! The textbook owns the teaching, so nothing here names an exam. The exam
//! side lives in the same module because it points at the sections, and the
//! reference always points one way.

use crate::{
    core::models::{Book, Chapter, ChapterExercise, ChapterSection, ExamRecallCheck, ExamTrap},
    error::AppError,
    state::DbState,
    store::{upstream, write::execute_write_local},
};

/// The bundle the import reads: the books and the chapters that belong to
/// them.
#[derive(Clone, Debug, serde::Deserialize)]
pub struct ChapterBundle {
    #[serde(default)]
    pub books: Vec<Book>,
    #[serde(default)]
    pub chapters: Vec<Chapter>,
}

fn json_of<T: serde::Serialize>(value: &T, column: &str) -> Result<String, AppError> {
    serde_json::to_string(value)
        .map_err(|e| AppError::Internal(format!("{column}: serialization failed: {e}")))
}

fn hash_of(value: &str) -> String {
    // A content hash that changes when the content changes, so a stale row is
    // findable. The bank uses sha256; the same job is done here.
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in value.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100_0000_01b3);
    }
    format!("{hash:016x}")
}

/// Write the books, chapters, sections, exercises and the exam side of a
/// bundle. The count is the number of chapters written.
pub async fn import_bundle(s: &DbState, bundle: &ChapterBundle) -> Result<usize, AppError> {
    for book in &bundle.books {
        import_book(s, book).await?;
    }
    for chapter in &bundle.chapters {
        import_chapter(s, chapter).await?;
    }
    Ok(bundle.chapters.len())
}

async fn import_book(s: &DbState, book: &Book) -> Result<(), AppError> {
    let parts = json_of(&book.parts, "books.parts")?;
    let sources = json_of(&book.sources, "books.sources")?;
    let hash = hash_of(&format!(
        "{}|{}|{}|{}|{}",
        book.id, book.title, book.subject_area, book.level, parts
    ));
    execute_write_local(
        s,
        "INSERT INTO books (id, title, subject_area, level, edition, description, parts, sources, content_hash) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9) \
         ON CONFLICT(id) DO UPDATE SET title = ?2, subject_area = ?3, level = ?4, edition = ?5, \
         description = ?6, parts = ?7, sources = ?8, content_hash = ?9, updated_at = CURRENT_TIMESTAMP",
        vec![
            turso::Value::Text(book.id.clone()),
            turso::Value::Text(book.title.clone()),
            turso::Value::Text(book.subject_area.clone()),
            turso::Value::Text(book.level.clone()),
            turso::Value::Text(book.edition.clone()),
            turso::Value::Text(book.description.clone()),
            turso::Value::Text(parts),
            turso::Value::Text(sources),
            turso::Value::Text(hash),
        ],
    )
    .await?;
    Ok(())
}

/// The stored id of a chapter's child object. The documents number their
/// sections and exercises from one, so the id is only unique inside the
/// chapter; the store needs it unique across the book.
fn namespaced(chapter_id: &str, local_id: &str) -> String {
    format!("{chapter_id}:{local_id}")
}

async fn import_chapter(s: &DbState, chapter: &Chapter) -> Result<(), AppError> {
    let objectives = json_of(&chapter.learning_objectives, "chapters.learning_objectives")?;
    let prerequisites = json_of(&chapter.prerequisites, "chapters.prerequisites")?;
    let formula_sheet = json_of(&chapter.formula_sheet, "chapters.formula_sheet")?;
    let glossary = json_of(&chapter.glossary, "chapters.glossary")?;
    let sources = json_of(&chapter.sources, "chapters.sources")?;
    let hash = hash_of(&format!(
        "{}|{}|{}|{}",
        chapter.chapter_id, objectives, glossary, chapter.order
    ));
    execute_write_local(
        s,
        "INSERT INTO chapters (chapter_id, book_id, part_id, order_index, title, schema_version, updated_at, \
         facts_inherited, learning_objectives, prerequisites, formula_sheet, glossary, sources, content_hash) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14) \
         ON CONFLICT(chapter_id) DO UPDATE SET book_id = ?2, part_id = ?3, order_index = ?4, title = ?5, schema_version = ?6, \
         updated_at = ?7, facts_inherited = ?8, learning_objectives = ?9, prerequisites = ?10, \
         formula_sheet = ?11, glossary = ?12, sources = ?13, content_hash = ?14",
        vec![
            turso::Value::Text(chapter.chapter_id.clone()),
            turso::Value::Text(chapter.book_id.clone()),
            match &chapter.part_id {
                Some(part) => turso::Value::Text(part.clone()),
                None => turso::Value::Null,
            },
            turso::Value::Integer(chapter.order),
            turso::Value::Text(chapter.title.clone()),
            turso::Value::Integer(i64::from(chapter.schema_version)),
            turso::Value::Text(chapter.updated_at.clone()),
            turso::Value::Integer(i64::from(chapter.facts_inherited)),
            turso::Value::Text(objectives),
            turso::Value::Text(prerequisites),
            turso::Value::Text(formula_sheet),
            turso::Value::Text(glossary),
            turso::Value::Text(sources),
            turso::Value::Text(hash),
        ],
    )
    .await?;

    for section in &chapter.sections {
        import_section(s, &chapter.chapter_id, section).await?;
    }
    for exercise in &chapter.exercises {
        import_exercise(s, &chapter.chapter_id, exercise).await?;
    }
    for trap in &chapter.exam_traps {
        import_trap(s, &chapter.chapter_id, trap).await?;
    }
    for check in &chapter.exam_recall_checks {
        import_recall_check(s, &chapter.chapter_id, check).await?;
    }
    Ok(())
}

async fn import_section(
    s: &DbState,
    chapter_id: &str,
    section: &ChapterSection,
) -> Result<(), AppError> {
    let objectives = json_of(
        &section.learning_objectives,
        "chapter_sections.learning_objectives",
    )?;
    let teaching_text = json_of(&section.teaching_text, "chapter_sections.teaching_text")?;
    let worked_examples = json_of(&section.worked_examples, "chapter_sections.worked_examples")?;
    let misconceptions = json_of(&section.misconceptions, "chapter_sections.misconceptions")?;
    let summary_points = json_of(&section.summary_points, "chapter_sections.summary_points")?;
    let exam_links = json_of(&section.exam_links, "chapter_sections.exam_links")?;
    let provenance = json_of(&section.provenance, "chapter_sections.provenance")?;
    let hash = hash_of(&format!(
        "{}|{}|{}",
        section.id, section.title, teaching_text
    ));
    let stored_id = namespaced(chapter_id, &section.id);
    execute_write_local(
        s,
        "INSERT INTO chapter_sections (id, chapter_id, order_index, slug, title, est_minutes, \
         facts_inherited, learning_objectives, teaching_text, worked_examples, misconceptions, \
         summary_points, exam_links, provenance, no_worked_example_reason, content_hash) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16) \
         ON CONFLICT(id) DO UPDATE SET chapter_id = ?2, order_index = ?3, slug = ?4, title = ?5, \
         est_minutes = ?6, facts_inherited = ?7, learning_objectives = ?8, teaching_text = ?9, \
         worked_examples = ?10, misconceptions = ?11, summary_points = ?12, exam_links = ?13, \
         provenance = ?14, no_worked_example_reason = ?15, content_hash = ?16, updated_at = CURRENT_TIMESTAMP",
        vec![
            turso::Value::Text(stored_id),
            turso::Value::Text(chapter_id.to_string()),
            turso::Value::Integer(section.order),
            turso::Value::Text(section.slug.clone()),
            turso::Value::Text(section.title.clone()),
            turso::Value::Integer(section.est_minutes),
            turso::Value::Integer(i64::from(section.facts_inherited)),
            turso::Value::Text(objectives),
            turso::Value::Text(teaching_text),
            turso::Value::Text(worked_examples),
            turso::Value::Text(misconceptions),
            turso::Value::Text(summary_points),
            turso::Value::Text(exam_links),
            turso::Value::Text(provenance),
            match &section.no_worked_example_reason {
                Some(reason) => turso::Value::Text(reason.clone()),
                None => turso::Value::Null,
            },
            turso::Value::Text(hash),
        ],
    )
    .await?;
    Ok(())
}

async fn import_exercise(
    s: &DbState,
    chapter_id: &str,
    exercise: &ChapterExercise,
) -> Result<(), AppError> {
    let stem = json_of(&exercise.stem, "chapter_exercises.stem")?;
    let options = json_of(&exercise.options, "chapter_exercises.options")?;
    let answer = json_of(&exercise.answer, "chapter_exercises.answer")?;
    let solution = json_of(&exercise.solution, "chapter_exercises.solution")?;
    let hints = json_of(&exercise.hints, "chapter_exercises.hints")?;
    let tags = json_of(&exercise.tags, "chapter_exercises.tags")?;
    let provenance = json_of(&exercise.provenance, "chapter_exercises.provenance")?;
    let hash = hash_of(&format!("{}|{}|{}", exercise.id, stem, answer));
    let stored_id = namespaced(chapter_id, &exercise.id);
    let stored_section = namespaced(chapter_id, &exercise.section_id);
    execute_write_local(
        s,
        "INSERT INTO chapter_exercises (id, chapter_id, section_id, tier, kind, difficulty, marks, \
         stem, options, answer, answer_kind, solution, hints, tags, provenance, solution_provenance, \
         answer_note, content_hash) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18) \
         ON CONFLICT(id) DO UPDATE SET chapter_id = ?2, section_id = ?3, tier = ?4, kind = ?5, \
         difficulty = ?6, marks = ?7, stem = ?8, options = ?9, answer = ?10, answer_kind = ?11, \
         solution = ?12, hints = ?13, tags = ?14, provenance = ?15, solution_provenance = ?16, \
         answer_note = ?17, content_hash = ?18, updated_at = CURRENT_TIMESTAMP",
        vec![
            turso::Value::Text(stored_id),
            turso::Value::Text(chapter_id.to_string()),
            turso::Value::Text(stored_section),
            turso::Value::Text(exercise.tier.clone()),
            turso::Value::Text(exercise.kind.clone()),
            turso::Value::Integer(exercise.difficulty),
            turso::Value::Real(exercise.marks),
            turso::Value::Text(stem),
            turso::Value::Text(options),
            turso::Value::Text(answer),
            turso::Value::Text(exercise.answer_kind.clone()),
            turso::Value::Text(solution),
            turso::Value::Text(hints),
            turso::Value::Text(tags),
            turso::Value::Text(provenance),
            turso::Value::Text(exercise.solution_provenance.clone()),
            match &exercise.answer_note {
                Some(note) => turso::Value::Text(note.clone()),
                None => turso::Value::Null,
            },
            turso::Value::Text(hash),
        ],
    )
    .await?;
    Ok(())
}

async fn import_trap(s: &DbState, chapter_id: &str, trap: &ExamTrap) -> Result<(), AppError> {
    let misconception = json_of(&trap.misconception, "exam_traps.misconception")?;
    let correction = json_of(&trap.correction, "exam_traps.correction")?;
    let signal = json_of(&trap.signal, "exam_traps.signal")?;
    let evidence = json_of(&trap.paper_evidence, "exam_traps.paper_evidence")?;
    let provenance = json_of(&trap.provenance, "exam_traps.provenance")?;
    let hash = hash_of(&format!("{}|{}|{}", trap.id, misconception, correction));
    let stored_id = namespaced(chapter_id, &trap.id);
    let stored_section = namespaced(chapter_id, &trap.section_id);
    execute_write_local(
        s,
        "INSERT INTO exam_traps (id, chapter_id, exam, subject, section_id, misconception, correction, \
         signal, status, paper_evidence, frequency, provenance, content_hash) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13) \
         ON CONFLICT(id) DO UPDATE SET chapter_id = ?2, exam = ?3, subject = ?4, section_id = ?5, \
         misconception = ?6, correction = ?7, signal = ?8, status = ?9, paper_evidence = ?10, \
         frequency = ?11, provenance = ?12, content_hash = ?13, updated_at = CURRENT_TIMESTAMP",
        vec![
            turso::Value::Text(stored_id),
            turso::Value::Text(chapter_id.to_string()),
            turso::Value::Text(trap.exam.clone()),
            turso::Value::Text(trap.subject.clone()),
            turso::Value::Text(stored_section),
            turso::Value::Text(misconception),
            turso::Value::Text(correction),
            turso::Value::Text(signal),
            turso::Value::Text(trap.status.clone()),
            turso::Value::Text(evidence),
            turso::Value::Text(trap.frequency.clone()),
            turso::Value::Text(provenance),
            turso::Value::Text(hash),
        ],
    )
    .await?;
    Ok(())
}

async fn import_recall_check(
    s: &DbState,
    chapter_id: &str,
    check: &ExamRecallCheck,
) -> Result<(), AppError> {
    let stem = json_of(&check.stem, "exam_recall_checks.stem")?;
    let options = json_of(&check.options, "exam_recall_checks.options")?;
    let explanation = json_of(&check.explanation, "exam_recall_checks.explanation")?;
    let hash = hash_of(&format!("{}|{}|{}", check.id, stem, check.answer));
    let stored_id = namespaced(chapter_id, &check.id);
    let stored_section = namespaced(chapter_id, &check.section_id);
    execute_write_local(
        s,
        "INSERT INTO exam_recall_checks (id, chapter_id, exam, subject, section_id, stem, options, \
         answer, explanation, difficulty, source, content_hash) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12) \
         ON CONFLICT(id) DO UPDATE SET chapter_id = ?2, exam = ?3, subject = ?4, section_id = ?5, \
         stem = ?6, options = ?7, answer = ?8, explanation = ?9, difficulty = ?10, source = ?11, \
         content_hash = ?12, updated_at = CURRENT_TIMESTAMP",
        vec![
            turso::Value::Text(stored_id),
            turso::Value::Text(chapter_id.to_string()),
            turso::Value::Text(check.exam.clone()),
            turso::Value::Text(check.subject.clone()),
            turso::Value::Text(stored_section),
            turso::Value::Text(stem),
            turso::Value::Text(options),
            turso::Value::Text(check.answer.clone()),
            turso::Value::Text(explanation),
            turso::Value::Integer(check.difficulty),
            turso::Value::Text(check.source.clone()),
            turso::Value::Text(hash),
        ],
    )
    .await?;
    Ok(())
}

/// Every book, with the number of chapters in each.
pub async fn list_books(s: &DbState) -> Result<Vec<Book>, AppError> {
    let rows = super::catalog::rows(
        s,
        "SELECT id, title, subject_area, level, edition, description, parts, sources FROM books ORDER BY title",
        vec![],
    )
    .await?;
    rows.iter().map(map_book).collect()
}

fn map_book(row: &turso::Row) -> Result<Book, AppError> {
    let id: String = row.get(0).map_err(upstream)?;
    let title: String = row.get(1).map_err(upstream)?;
    let subject_area: String = row.get(2).map_err(upstream)?;
    let level: String = row.get(3).map_err(upstream)?;
    let edition: String = row.get(4).map_err(upstream)?;
    let description: String = row.get(5).map_err(upstream)?;
    let parts_raw: String = row.get(6).map_err(upstream)?;
    let sources_raw: String = row.get(7).map_err(upstream)?;
    Ok(Book {
        id,
        title,
        subject_area,
        level,
        edition,
        description,
        parts: super::catalog::json_col(&parts_raw, "books.parts")?,
        sources: super::catalog::json_col(&sources_raw, "books.sources")?,
    })
}

/// The short shape of a chapter, for a listing.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ChapterSummary {
    pub chapter_id: String,
    pub title: String,
    pub part_id: Option<String>,
    pub sections: i64,
    pub exercises: i64,
    pub est_minutes: i64,
}

/// One book and the chapters it holds.
pub async fn get_book(
    s: &DbState,
    book_id: &str,
) -> Result<Option<(Book, Vec<ChapterSummary>)>, AppError> {
    let Some(book) = list_books(s)
        .await?
        .into_iter()
        .find(|book| book.id == book_id)
    else {
        return Ok(None);
    };
    let chapters = list_chapters(s, book_id).await?;
    Ok(Some((book, chapters)))
}

/// The chapters of a book.
pub async fn list_chapters(s: &DbState, book_id: &str) -> Result<Vec<ChapterSummary>, AppError> {
    let rows = super::catalog::rows(
        s,
        "SELECT c.chapter_id, c.title, c.part_id, \
         (SELECT COUNT(*) FROM chapter_sections s WHERE s.chapter_id = c.chapter_id) AS sections, \
         (SELECT COUNT(*) FROM chapter_exercises e WHERE e.chapter_id = c.chapter_id) AS exercises, \
         (SELECT COALESCE(SUM(s2.est_minutes), 0) FROM chapter_sections s2 WHERE s2.chapter_id = c.chapter_id) AS est_minutes \
         FROM chapters c WHERE c.book_id = ?1 ORDER BY c.order_index, c.title",
        vec![turso::Value::Text(book_id.to_string())],
    )
    .await?;
    rows.iter().map(map_chapter_summary).collect()
}

fn map_chapter_summary(row: &turso::Row) -> Result<ChapterSummary, AppError> {
    let chapter_id: String = row.get(0).map_err(upstream)?;
    let title: String = row.get(1).map_err(upstream)?;
    let part_id =
        super::catalog::opt_string(row.get_value(2).map_err(upstream)?, "chapters.part_id")?;
    let sections: i64 = row.get(3).map_err(upstream)?;
    let exercises: i64 = row.get(4).map_err(upstream)?;
    let est_minutes: i64 = row.get(5).map_err(upstream)?;
    Ok(ChapterSummary {
        chapter_id,
        title,
        part_id,
        sections,
        exercises,
        est_minutes,
    })
}

/// One chapter, with its sections, its exercises and its exam side.
pub async fn get_chapter(s: &DbState, chapter_id: &str) -> Result<Option<Chapter>, AppError> {
    let Some(row) = super::catalog::rows(
        s,
        "SELECT chapter_id, book_id, part_id, title, schema_version, updated_at, facts_inherited, \
         learning_objectives, prerequisites, formula_sheet, glossary, sources, order_index \
         FROM chapters WHERE chapter_id = ?1",
        vec![turso::Value::Text(chapter_id.to_string())],
    )
    .await?
    .into_iter()
    .next() else {
        return Ok(None);
    };

    let chapter_id: String = row.get(0).map_err(upstream)?;
    let book_id: String = row.get(1).map_err(upstream)?;
    let part_id =
        super::catalog::opt_string(row.get_value(2).map_err(upstream)?, "chapters.part_id")?;
    let title: String = row.get(3).map_err(upstream)?;
    let schema_version: i64 = row.get(4).map_err(upstream)?;
    let updated_at: String = row.get(5).map_err(upstream)?;
    let facts_inherited: i64 = row.get(6).map_err(upstream)?;
    let objectives_raw: String = row.get(7).map_err(upstream)?;
    let prerequisites_raw: String = row.get(8).map_err(upstream)?;
    let formula_sheet_raw: String = row.get(9).map_err(upstream)?;
    let glossary_raw: String = row.get(10).map_err(upstream)?;
    let sources_raw: String = row.get(11).map_err(upstream)?;
    let order: i64 = row.get(12).map_err(upstream)?;

    let section_rows = super::catalog::rows(
        s,
        "SELECT id, order_index, slug, title, est_minutes, facts_inherited, learning_objectives, \
         teaching_text, worked_examples, misconceptions, summary_points, exam_links, provenance, \
         no_worked_example_reason FROM chapter_sections WHERE chapter_id = ?1 ORDER BY order_index",
        vec![turso::Value::Text(chapter_id.clone())],
    )
    .await?;

    let exercise_rows = super::catalog::rows(
        s,
        "SELECT id, section_id, tier, kind, difficulty, marks, stem, options, answer, answer_kind, \
         solution, hints, tags, provenance, solution_provenance, answer_note \
         FROM chapter_exercises WHERE chapter_id = ?1 ORDER BY section_id, id",
        vec![turso::Value::Text(chapter_id.clone())],
    )
    .await?;

    let trap_rows = super::catalog::rows(
        s,
        "SELECT id, exam, subject, section_id, misconception, correction, signal, status, \
         paper_evidence, frequency, provenance FROM exam_traps WHERE chapter_id = ?1 ORDER BY id",
        vec![turso::Value::Text(chapter_id.clone())],
    )
    .await?;

    let check_rows = super::catalog::rows(
        s,
        "SELECT id, exam, subject, section_id, stem, options, answer, explanation, difficulty, source \
         FROM exam_recall_checks WHERE chapter_id = ?1 ORDER BY id",
        vec![turso::Value::Text(chapter_id.clone())],
    )
    .await?;

    let exercises = exercise_rows
        .iter()
        .map(map_exercise)
        .collect::<Result<Vec<ChapterExercise>, AppError>>()?;
    let mut sections = section_rows
        .iter()
        .map(map_section)
        .collect::<Result<Vec<ChapterSection>, AppError>>()?;
    // The section holds the ids of its own exercises, so a reader can walk
    // the chapter without loading all of them.
    for section in sections.iter_mut() {
        section.exercise_ids = exercises
            .iter()
            .filter(|exercise| exercise.section_id == section.id)
            .map(|exercise| exercise.id.clone())
            .collect();
    }

    Ok(Some(Chapter {
        chapter_id,
        schema_version: schema_version as u32,
        updated_at,
        title,
        book_id,
        part_id,
        order,
        facts_inherited: facts_inherited != 0,
        learning_objectives: super::catalog::json_col(
            &objectives_raw,
            "chapters.learning_objectives",
        )?,
        prerequisites: super::catalog::json_col(&prerequisites_raw, "chapters.prerequisites")?,
        formula_sheet: super::catalog::json_col(&formula_sheet_raw, "chapters.formula_sheet")?,
        glossary: super::catalog::json_col(&glossary_raw, "chapters.glossary")?,
        sources: super::catalog::json_col(&sources_raw, "chapters.sources")?,
        sections,
        exercises,
        exam_traps: trap_rows
            .iter()
            .map(map_trap)
            .collect::<Result<Vec<ExamTrap>, AppError>>()?,
        exam_recall_checks: check_rows
            .iter()
            .map(map_check)
            .collect::<Result<Vec<ExamRecallCheck>, AppError>>()?,
    }))
}

/// One section by id or slug within a chapter.
pub async fn get_section(
    s: &DbState,
    chapter_id: &str,
    section_id: &str,
) -> Result<Option<ChapterSection>, AppError> {
    let namespaced_id = namespaced(chapter_id, section_id);
    let rows = super::catalog::rows(
        s,
        "SELECT id, order_index, slug, title, est_minutes, facts_inherited, learning_objectives, \
         teaching_text, worked_examples, misconceptions, summary_points, exam_links, provenance, \
         no_worked_example_reason FROM chapter_sections \
         WHERE chapter_id = ?1 AND (id = ?2 OR id = ?3 OR slug = ?2) LIMIT 1",
        vec![
            turso::Value::Text(chapter_id.to_string()),
            turso::Value::Text(section_id.to_string()),
            turso::Value::Text(namespaced_id),
        ],
    )
    .await?;

    let Some(row) = rows.into_iter().next() else {
        return Ok(None);
    };

    let mut section = map_section(&row)?;
    let exercise_rows = super::catalog::rows(
        s,
        "SELECT id FROM chapter_exercises WHERE chapter_id = ?1 AND section_id = ?2 ORDER BY id",
        vec![
            turso::Value::Text(chapter_id.to_string()),
            turso::Value::Text(section.id.clone()),
        ],
    )
    .await?;

    section.exercise_ids = exercise_rows
        .into_iter()
        .filter_map(|r| r.get::<String>(0).ok())
        .collect();

    Ok(Some(section))
}

fn map_section(row: &turso::Row) -> Result<ChapterSection, AppError> {
    let id: String = row.get(0).map_err(upstream)?;
    let order: i64 = row.get(1).map_err(upstream)?;
    let slug: String = row.get(2).map_err(upstream)?;
    let title: String = row.get(3).map_err(upstream)?;
    let est_minutes: i64 = row.get(4).map_err(upstream)?;
    let facts_inherited: i64 = row.get(5).map_err(upstream)?;
    let objectives_raw: String = row.get(6).map_err(upstream)?;
    let teaching_text_raw: String = row.get(7).map_err(upstream)?;
    let worked_examples_raw: String = row.get(8).map_err(upstream)?;
    let misconceptions_raw: String = row.get(9).map_err(upstream)?;
    let summary_points_raw: String = row.get(10).map_err(upstream)?;
    let exam_links_raw: String = row.get(11).map_err(upstream)?;
    let provenance_raw: String = row.get(12).map_err(upstream)?;
    let no_worked_example_reason = super::catalog::opt_string(
        row.get_value(13).map_err(upstream)?,
        "chapter_sections.no_worked_example_reason",
    )?;
    Ok(ChapterSection {
        id,
        order,
        slug,
        title,
        est_minutes,
        facts_inherited: facts_inherited != 0,
        learning_objectives: super::catalog::json_col(
            &objectives_raw,
            "chapter_sections.learning_objectives",
        )?,
        teaching_text: super::catalog::json_col(
            &teaching_text_raw,
            "chapter_sections.teaching_text",
        )?,
        worked_examples: super::catalog::json_col(
            &worked_examples_raw,
            "chapter_sections.worked_examples",
        )?,
        misconceptions: super::catalog::json_col(
            &misconceptions_raw,
            "chapter_sections.misconceptions",
        )?,
        summary_points: super::catalog::json_col(
            &summary_points_raw,
            "chapter_sections.summary_points",
        )?,
        exercise_ids: Vec::new(),
        exam_links: super::catalog::json_col(&exam_links_raw, "chapter_sections.exam_links")?,
        provenance: super::catalog::json_col(&provenance_raw, "chapter_sections.provenance")?,
        no_worked_example_reason,
    })
}

fn map_exercise(row: &turso::Row) -> Result<ChapterExercise, AppError> {
    let id: String = row.get(0).map_err(upstream)?;
    let section_id: String = row.get(1).map_err(upstream)?;
    let tier: String = row.get(2).map_err(upstream)?;
    let kind: String = row.get(3).map_err(upstream)?;
    let difficulty: i64 = row.get(4).map_err(upstream)?;
    let marks: f64 = row.get(5).map_err(upstream)?;
    let stem_raw: String = row.get(6).map_err(upstream)?;
    let options_raw: String = row.get(7).map_err(upstream)?;
    let answer_raw: String = row.get(8).map_err(upstream)?;
    let answer_kind: String = row.get(9).map_err(upstream)?;
    let solution_raw: String = row.get(10).map_err(upstream)?;
    let hints_raw: String = row.get(11).map_err(upstream)?;
    let tags_raw: String = row.get(12).map_err(upstream)?;
    let provenance_raw: String = row.get(13).map_err(upstream)?;
    let solution_provenance: String = row.get(14).map_err(upstream)?;
    let answer_note = super::catalog::opt_string(
        row.get_value(15).map_err(upstream)?,
        "chapter_exercises.answer_note",
    )?;
    Ok(ChapterExercise {
        id,
        section_id,
        tier,
        kind,
        difficulty,
        marks,
        stem: super::catalog::json_col(&stem_raw, "chapter_exercises.stem")?,
        options: super::catalog::json_col(&options_raw, "chapter_exercises.options")?,
        answer: super::catalog::json_col(&answer_raw, "chapter_exercises.answer")?,
        answer_kind,
        solution: super::catalog::json_col(&solution_raw, "chapter_exercises.solution")?,
        hints: super::catalog::json_col(&hints_raw, "chapter_exercises.hints")?,
        tags: super::catalog::json_col(&tags_raw, "chapter_exercises.tags")?,
        provenance: super::catalog::json_col(&provenance_raw, "chapter_exercises.provenance")?,
        solution_provenance,
        answer_note,
    })
}

fn map_trap(row: &turso::Row) -> Result<ExamTrap, AppError> {
    let id: String = row.get(0).map_err(upstream)?;
    let exam: String = row.get(1).map_err(upstream)?;
    let subject: String = row.get(2).map_err(upstream)?;
    let section_id: String = row.get(3).map_err(upstream)?;
    let misconception_raw: String = row.get(4).map_err(upstream)?;
    let correction_raw: String = row.get(5).map_err(upstream)?;
    let signal_raw: String = row.get(6).map_err(upstream)?;
    let status: String = row.get(7).map_err(upstream)?;
    let evidence_raw: String = row.get(8).map_err(upstream)?;
    let frequency: String = row.get(9).map_err(upstream)?;
    let provenance_raw: String = row.get(10).map_err(upstream)?;
    Ok(ExamTrap {
        id,
        exam,
        subject,
        section_id,
        misconception: super::catalog::json_col(&misconception_raw, "exam_traps.misconception")?,
        correction: super::catalog::json_col(&correction_raw, "exam_traps.correction")?,
        signal: super::catalog::json_col(&signal_raw, "exam_traps.signal")?,
        status,
        paper_evidence: super::catalog::json_col(&evidence_raw, "exam_traps.paper_evidence")?,
        frequency,
        provenance: super::catalog::json_col(&provenance_raw, "exam_traps.provenance")?,
    })
}

fn map_check(row: &turso::Row) -> Result<ExamRecallCheck, AppError> {
    let id: String = row.get(0).map_err(upstream)?;
    let exam: String = row.get(1).map_err(upstream)?;
    let subject: String = row.get(2).map_err(upstream)?;
    let section_id: String = row.get(3).map_err(upstream)?;
    let stem_raw: String = row.get(4).map_err(upstream)?;
    let options_raw: String = row.get(5).map_err(upstream)?;
    let answer: String = row.get(6).map_err(upstream)?;
    let explanation_raw: String = row.get(7).map_err(upstream)?;
    let difficulty: i64 = row.get(8).map_err(upstream)?;
    let source: String = row.get(9).map_err(upstream)?;
    Ok(ExamRecallCheck {
        id,
        exam,
        subject,
        section_id,
        stem: super::catalog::json_col(&stem_raw, "exam_recall_checks.stem")?,
        options: super::catalog::json_col(&options_raw, "exam_recall_checks.options")?,
        answer,
        explanation: super::catalog::json_col(&explanation_raw, "exam_recall_checks.explanation")?,
        difficulty,
        source,
    })
}

/// The exercises of a chapter, optionally narrowed to one section or one tier.
pub async fn list_exercises(
    s: &DbState,
    chapter_id: &str,
    section_id: Option<&str>,
    tier: Option<&str>,
) -> Result<Vec<ChapterExercise>, AppError> {
    let mut sql = String::from(
        "SELECT id, section_id, tier, kind, difficulty, marks, stem, options, answer, answer_kind, \
         solution, hints, tags, provenance, solution_provenance, answer_note \
         FROM chapter_exercises WHERE chapter_id = ?1",
    );
    let mut args = vec![turso::Value::Text(chapter_id.to_string())];
    if let Some(section) = section_id {
        sql.push_str(&format!(" AND section_id = ?{}", args.len() + 1));
        args.push(turso::Value::Text(section.to_string()));
    }
    if let Some(tier) = tier {
        sql.push_str(&format!(" AND tier = ?{}", args.len() + 1));
        args.push(turso::Value::Text(tier.to_string()));
    }
    sql.push_str(" ORDER BY section_id, id");

    let rows = super::catalog::rows(s, &sql, args).await?;
    rows.iter().map(map_exercise).collect()
}

/// The traps of an exam, or of one section.
pub async fn list_traps(
    s: &DbState,
    exam: Option<&str>,
    section_id: Option<&str>,
) -> Result<Vec<ExamTrap>, AppError> {
    let mut sql = String::from(
        "SELECT id, exam, subject, section_id, misconception, correction, signal, status, \
         paper_evidence, frequency, provenance FROM exam_traps WHERE 1 = 1",
    );
    let mut args = Vec::new();
    if let Some(exam) = exam {
        sql.push_str(&format!(" AND exam = ?{}", args.len() + 1));
        args.push(turso::Value::Text(exam.to_string()));
    }
    if let Some(section) = section_id {
        sql.push_str(&format!(" AND section_id = ?{}", args.len() + 1));
        args.push(turso::Value::Text(section.to_string()));
    }
    sql.push_str(" ORDER BY exam, section_id, id");

    let rows = super::catalog::rows(s, &sql, args).await?;
    rows.iter().map(map_trap).collect()
}

/// The practice items written in an exam's own wording.
pub async fn list_recall_checks(
    s: &DbState,
    exam: Option<&str>,
    section_id: Option<&str>,
) -> Result<Vec<ExamRecallCheck>, AppError> {
    let mut sql = String::from(
        "SELECT id, exam, subject, section_id, stem, options, answer, explanation, difficulty, source \
         FROM exam_recall_checks WHERE 1 = 1",
    );
    let mut args = Vec::new();
    if let Some(exam) = exam {
        sql.push_str(&format!(" AND exam = ?{}", args.len() + 1));
        args.push(turso::Value::Text(exam.to_string()));
    }
    if let Some(section) = section_id {
        sql.push_str(&format!(" AND section_id = ?{}", args.len() + 1));
        args.push(turso::Value::Text(section.to_string()));
    }
    sql.push_str(" ORDER BY exam, section_id, id");

    let rows = super::catalog::rows(s, &sql, args).await?;
    rows.iter().map(map_check).collect()
}

#[cfg(test)]
mod tests {
    use super::ChapterBundle;
    use crate::{
        core::models::{
            Book, BookPart, Chapter, ChapterExercise, ChapterSection, ContentBlock,
            ExamTrap, ExerciseSolutionStep, PaperEvidence, Provenance, RichText,
            TeachingTextContainer,
        },
        testing::{api_schema, connect, replica},
    };

    fn a_book() -> Book {
        Book {
            id: "secondary_physics".into(),
            title: "Secondary Physics".into(),
            subject_area: "physics".into(),
            level: "secondary".into(),
            edition: "draft-1".into(),
            description: "The physics a senior secondary student needs.".into(),
            parts: vec![BookPart {
                id: "part-1".into(),
                order: 1,
                title: "Motion and Force".into(),
            }],
            sources: vec![],
        }
    }

    fn a_chapter() -> Chapter {
        Chapter {
            chapter_id: "phy_forces_and_newtons_laws".into(),
            schema_version: 2,
            updated_at: "2026-11-12".into(),
            title: "Forces and Newton's Laws of Motion".into(),
            book_id: "secondary_physics".into(),
            part_id: Some("part-1".into()),
            order: 4,
            facts_inherited: true,
            learning_objectives: vec![],
            prerequisites: vec![],
            formula_sheet: vec![],
            glossary: vec![],
            sources: vec![],
            sections: vec![ChapterSection {
                id: "sec-1".into(),
                order: 1,
                slug: "introduction".into(),
                title: "Introduction".into(),
                est_minutes: 10,
                facts_inherited: true,
                learning_objectives: vec![],
                teaching_text: TeachingTextContainer::Wrapped {
                    blocks: vec![ContentBlock::Paragraph {
                        id: "p-1".into(),
                        text: RichText {
                            text: "Introduction to forces".into(),
                            inline: vec![],
                        },
                    }],
                },
                worked_examples: vec![],
                misconceptions: vec![],
                summary_points: vec![],
                exercise_ids: vec![],
                exam_links: vec![],
                provenance: Provenance::default(),
                no_worked_example_reason: None,
            }],
            exercises: vec![ChapterExercise {
                id: "ex-sec-1-01".into(),
                section_id: "sec-1".into(),
                tier: "core".into(),
                kind: "numeric".into(),
                difficulty: 3,
                marks: 2.0,
                stem: RichText {
                    text: "A 2 kg body moves at 6 m/s. Its kinetic energy is".into(),
                    inline: vec![],
                },
                options: vec![],
                answer: RichText {
                    text: "36 J".into(),
                    inline: vec![],
                },
                answer_kind: "expression".into(),
                solution: vec![ExerciseSolutionStep {
                    step_number: 1,
                    expression: "K = 1/2 mv^2 = 36 J".into(),
                }],
                hints: vec![],
                tags: vec!["kinetic-energy".into()],
                provenance: Provenance::default(),
                solution_provenance: "OpenStax".into(),
                answer_note: None,
            }],
            exam_traps: vec![ExamTrap {
                id: "trap-1".into(),
                exam: "JAMB".into(),
                subject: "physics".into(),
                section_id: "sec-1".into(),
                misconception: RichText {
                    text: "A body cannot exert a force on itself.".into(),
                    inline: vec![],
                },
                correction: RichText {
                    text: "It cannot. The hawk is pushed by the air.".into(),
                    inline: vec![],
                },
                signal: RichText {
                    text: "our own teaching".into(),
                    inline: vec![],
                },
                status: "candidate".into(),
                paper_evidence: Some(PaperEvidence {
                    section_id: Some("sec-1".into()),
                    ..Default::default()
                }),
                frequency: "candidate".into(),
                provenance: Provenance::default(),
            }],
            exam_recall_checks: vec![],
        }
    }

    async fn state() -> crate::state::DbState {
        let db = replica().await;
        {
            let conn = connect(&db).await;
            api_schema(&conn).await;
        }
        crate::state::DbState::detached(db)
    }

    #[tokio::test]
    async fn a_bundle_lands_and_reads_back() {
        let state = state().await;
        let bundle = ChapterBundle {
            books: vec![a_book()],
            chapters: vec![a_chapter()],
        };

        let written = super::import_bundle(&state, &bundle).await.expect("import");
        assert_eq!(written, 1);

        let books = super::list_books(&state).await.expect("books");
        assert_eq!(books.len(), 1);
        assert_eq!(books[0].title, "Secondary Physics");
        assert_eq!(books[0].parts.len(), 1);

        let (book, listed) = super::get_book(&state, "secondary_physics")
            .await
            .expect("book")
            .expect("the book is there");
        assert_eq!(book.id, "secondary_physics");
        assert_eq!(listed.len(), 1);
        assert_eq!(listed[0].sections, 1);
        assert_eq!(listed[0].exercises, 1);

        let chapter = super::get_chapter(&state, "phy_forces_and_newtons_laws")
            .await
            .expect("chapter")
            .expect("the chapter is there");
        assert_eq!(chapter.title, "Forces and Newton's Laws of Motion");
        assert_eq!(chapter.sections.len(), 1);
        assert_eq!(chapter.exercises.len(), 1);
        assert_eq!(chapter.exam_traps.len(), 1);
        // The section carries the ids of its own exercises, and every stored
        // id is namespaced by its chapter so the book has no collisions.
        assert_eq!(
            chapter.sections[0].exercise_ids,
            vec!["phy_forces_and_newtons_laws:ex-sec-1-01".to_string()]
        );
        assert_eq!(chapter.sections[0].id, "phy_forces_and_newtons_laws:sec-1");

        let sec_local = super::get_section(&state, "phy_forces_and_newtons_laws", "sec-1")
            .await
            .expect("section")
            .expect("sec-1 found by local id");
        assert_eq!(sec_local.title, "Introduction");
        assert_eq!(sec_local.exercise_ids.len(), 1);

        let sec_namespaced = super::get_section(
            &state,
            "phy_forces_and_newtons_laws",
            "phy_forces_and_newtons_laws:sec-1",
        )
        .await
        .expect("section")
        .expect("sec-1 found by namespaced id");
        assert_eq!(sec_namespaced.id, "phy_forces_and_newtons_laws:sec-1");
    }

    #[tokio::test]
    async fn chapters_are_listed_in_book_order() {
        let state = state().await;
        let mut later = a_chapter();
        later.chapter_id = "phy_later".into();
        later.title = "Zulu Chapter".into();
        later.order = 1;
        let mut earlier = a_chapter();
        earlier.chapter_id = "phy_earlier".into();
        earlier.title = "Alpha Chapter".into();
        earlier.order = 2;

        let bundle = ChapterBundle {
            books: vec![a_book()],
            chapters: vec![earlier, later],
        };
        super::import_bundle(&state, &bundle).await.expect("import");

        let listed = super::list_chapters(&state, "secondary_physics")
            .await
            .expect("chapters");
        let titles: Vec<&str> = listed
            .iter()
            .map(|chapter| chapter.title.as_str())
            .collect();
        assert_eq!(titles, vec!["Zulu Chapter", "Alpha Chapter"]);
    }

    #[tokio::test]
    async fn an_import_twice_does_not_duplicate() {
        let state = state().await;
        let bundle = ChapterBundle {
            books: vec![a_book()],
            chapters: vec![a_chapter()],
        };
        super::import_bundle(&state, &bundle).await.expect("first");
        super::import_bundle(&state, &bundle).await.expect("second");

        assert_eq!(super::list_books(&state).await.expect("books").len(), 1);
        let chapter = super::get_chapter(&state, "phy_forces_and_newtons_laws")
            .await
            .expect("chapter")
            .expect("the chapter is there");
        assert_eq!(chapter.sections.len(), 1);
        assert_eq!(chapter.exercises.len(), 1);
        assert_eq!(chapter.exam_traps.len(), 1);
    }

    #[tokio::test]
    async fn exercises_can_be_narrowed_to_a_section_or_a_tier() {
        let state = state().await;
        let bundle = ChapterBundle {
            books: vec![a_book()],
            chapters: vec![a_chapter()],
        };
        super::import_bundle(&state, &bundle).await.expect("import");

        let all = super::list_exercises(&state, "phy_forces_and_newtons_laws", None, None)
            .await
            .expect("exercises");
        assert_eq!(all.len(), 1);

        let by_section = super::list_exercises(
            &state,
            "phy_forces_and_newtons_laws",
            Some("phy_forces_and_newtons_laws:sec-1"),
            None,
        )
        .await
        .expect("exercises");
        assert_eq!(by_section.len(), 1);

        let by_tier =
            super::list_exercises(&state, "phy_forces_and_newtons_laws", None, Some("core"))
                .await
                .expect("exercises");
        assert_eq!(by_tier.len(), 1);

        let other_tier =
            super::list_exercises(&state, "phy_forces_and_newtons_laws", None, Some("stretch"))
                .await
                .expect("exercises");
        assert!(other_tier.is_empty());
    }

    #[tokio::test]
    async fn traps_can_be_narrowed_to_an_exam() {
        let state = state().await;
        let bundle = ChapterBundle {
            books: vec![a_book()],
            chapters: vec![a_chapter()],
        };
        super::import_bundle(&state, &bundle).await.expect("import");

        let jamb = super::list_traps(&state, Some("JAMB"), None)
            .await
            .expect("traps");
        assert_eq!(jamb.len(), 1);
        assert_eq!(jamb[0].status, "candidate");

        let waec = super::list_traps(&state, Some("WAEC"), None)
            .await
            .expect("traps");
        assert!(waec.is_empty());
    }
}
