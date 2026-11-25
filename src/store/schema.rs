//! Single source of truth for production shapes.
//!
//! The pipeline stages whatever it wants in its own database, but what
//! lands in the production database must match this file. Two guards,
//! because drift can travel in two directions:
//!
//! - `contract_version` is the pipeline's announcement. A version the
//!   server does not know fails loudly instead of serving misshapen rows.
//! - `READ_SHAPES` is the server's own dependency list. `check_shapes`
//!   probes the replica on every boot and re-check, and fails closed when
//!   a table or column we read is absent, so a shape the pipeline changed
//!   without announcing it is caught anyway.
//!
//! `DDL` creates the tables the API owns. API-owned changes after the initial
//! shape go through the numbered migrations below. The bank tables (questions,
//! subjects, passages, …) are owned and created by the pipeline, so the
//! API never creates them: they are declared here as reads, not DDL.

use super::{upstream, with_conn};
use crate::{error::AppError, state::DbState};

/// Bump when a production shape changes. The pipeline stamps what it
/// promoted against; anything else fails the version half of the check.
pub const CONTRACT_VERSION: u64 = 1;

/// Version of the API-owned schema. This is separate from
/// [`CONTRACT_VERSION`], which belongs to the content pipeline.
pub const API_SCHEMA_VERSION: u64 = 19;

/// Tables the API owns and creates at boot.
pub(crate) const DDL: &[&str] = &[
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS api_schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS api_keys (prefix TEXT PRIMARY KEY, hash TEXT NOT NULL, tier TEXT NOT NULL DEFAULT 'commercial', scopes TEXT NOT NULL DEFAULT 'read:catalog', revoked INTEGER NOT NULL DEFAULT 0, owner TEXT NOT NULL DEFAULT '', idempotency_hash TEXT UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS dashboard_users (username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'customer', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS api_access_tokens (token_hash TEXT PRIMARY KEY, parent_prefix TEXT NOT NULL, scopes TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL, reporter TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT, created_at INTEGER NOT NULL, UNIQUE(reporter, target_type, target_id, reason))",
    "CREATE TABLE IF NOT EXISTS lessons (id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'published', title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '{}', subject TEXT NOT NULL, level TEXT NOT NULL DEFAULT '', estimated_minutes INTEGER NOT NULL DEFAULT 0, objectives TEXT NOT NULL DEFAULT '[]', content TEXT NOT NULL DEFAULT '[]', checks TEXT NOT NULL DEFAULT '[]', misconceptions TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '[]', example_question_refs TEXT NOT NULL DEFAULT '[]', provenance TEXT NOT NULL DEFAULT '{}', content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS theory_questions (id TEXT PRIMARY KEY, exam TEXT NOT NULL, subject TEXT NOT NULL, year INTEGER NOT NULL, paper INTEGER NOT NULL DEFAULT 2, section TEXT NOT NULL, question_number TEXT NOT NULL, topic_slug TEXT NOT NULL, subtopic_slug TEXT, total_marks INTEGER NOT NULL, stem TEXT NOT NULL, diagram_url TEXT, sub_parts TEXT NOT NULL DEFAULT '[]', formulation_bridge TEXT NOT NULL DEFAULT '[]', marking_methods TEXT NOT NULL DEFAULT '[]', diagram_rubric TEXT, penalties TEXT NOT NULL DEFAULT '[]', examiner_report TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
];

/// Indexes the API owns. Kept out of [`DDL`] because that list is the table
/// shape contract; these are applied after migrations so an upgrade can
/// collapse duplicates before the unique ones exist.
pub(crate) const INDEXES: &[&str] = &[
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_idempotency_hash ON api_keys(idempotency_hash)",
    "CREATE INDEX IF NOT EXISTS idx_access_tokens_parent ON api_access_tokens(parent_prefix)",
    "CREATE INDEX IF NOT EXISTS idx_access_tokens_expiry ON api_access_tokens(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_theory_lookup ON theory_questions (exam, subject, topic_slug)",
    "CREATE INDEX IF NOT EXISTS idx_theory_year_lookup ON theory_questions (exam, subject, year)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_theory_unique ON theory_questions (exam, subject, year, paper, question_number)",
];

/// Every table the store reads, and the columns it depends on. This is the
/// list `check_shapes` enforces against the live replica. A table with no
/// columns asserted (`countries`) only needs to exist, because the meta
/// surface reads it with `SELECT *`.
///
/// When a reader starts depending on a new column, add it here in the same
/// change. The test below fails otherwise only if the table itself is new,
/// so treat this list as part of the reader's definition, not paperwork.
pub const READ_SHAPES: &[(&str, &[&str])] = &[
    // Account tables the API owns.
    ("meta", &["key", "value"]),
    (
        "lessons",
        &[
            "id",
            "status",
            "title",
            "description",
            "subject",
            "level",
            "estimated_minutes",
            "objectives",
            "content",
            "checks",
            "misconceptions",
            "summary",
            "example_question_refs",
            "provenance",
            "content_hash",
        ],
    ),
    ("api_schema_migrations", &["version", "applied_at"]),
    (
        "api_keys",
        &[
            "prefix",
            "hash",
            "tier",
            "scopes",
            "revoked",
            "owner",
            "created_at",
        ],
    ),
    (
        "dashboard_users",
        &["username", "pw_hash", "role", "created_at"],
    ),
    ("sessions", &["token_hash", "username", "expires_at"]),
    (
        "api_access_tokens",
        &[
            "token_hash",
            "parent_prefix",
            "scopes",
            "expires_at",
            "revoked",
            "created_at",
        ],
    ),
    (
        "reports",
        &[
            "id",
            "target_type",
            "target_id",
            "reporter",
            "reason",
            "detail",
            "created_at",
        ],
    ),
    (
        "theory_questions",
        &[
            "id",
            "exam",
            "subject",
            "year",
            "paper",
            "section",
            "question_number",
            "topic_slug",
            "subtopic_slug",
            "total_marks",
            "stem",
            "diagram_url",
            "sub_parts",
            "formulation_bridge",
            "marking_methods",
            "diagram_rubric",
            "penalties",
            "examiner_report",
            "content_hash",
        ],
    ),
    // Bank tables the pipeline owns.
    (
        "exams",
        &[
            "code",
            "name",
            "countries",
            "status",
            "has_full_paper",
            "subjects_required",
            "duration_minutes",
            "rules",
        ],
    ),
    (
        "exam_requirements",
        &["exam", "country", "group", "min_select", "subjects"],
    ),
    (
        "subjects",
        &[
            "slug",
            "exam",
            "name",
            "order",
            "is_compulsory",
            "objective_paper_questions",
            "countries",
            "syllabus_exam",
            "syllabus_subject",
        ],
    ),
    (
        "topics",
        &[
            "slug",
            "subject",
            "exam",
            "name",
            "order",
            "weight",
            "objectives",
            "countries",
            "lesson_refs",
        ],
    ),
    (
        "subtopics",
        &[
            "slug",
            "topic",
            "name",
            "order",
            "objectives",
            "lesson_refs",
        ],
    ),
    ("countries", &[]),
    (
        "questions",
        &[
            "id",
            "exam",
            "subject",
            "year",
            "source",
            "text",
            "inline",
            "options",
            "answer",
            "subtopic_id",
            "section",
            "passage_id",
            "explanation",
            "marks",
            "difficulty",
            "content_hash",
        ],
    ),
    (
        "verifications",
        &[
            "id",
            "question_id",
            "kind",
            "verdict",
            "scope",
            "verifier",
            "detail",
            "content_hash",
            "created_at",
        ],
    ),
    (
        "passages",
        &[
            "id", "exam", "subject", "year", "kind", "title", "author", "text", "inline",
        ],
    ),
    (
        "novels",
        &[
            "id",
            "title",
            "author",
            "year_published",
            "exam",
            "year_prescribed",
            "category",
            "featured",
            "synopsis",
            "setting_place",
            "setting_period",
            "cover_image",
        ],
    ),
    (
        "novel_chapters",
        &["novel_id", "number", "title", "summary", "key_events"],
    ),
    (
        "novel_characters",
        &["novel_id", "name", "role", "character_type", "description"],
    ),
    (
        "novel_themes",
        &["novel_id", "name", "description", "evidence"],
    ),
    (
        "novel_questions",
        &[
            "id",
            "novel_id",
            "chapter_number",
            "text",
            "inline",
            "options",
            "answer",
            "explanation",
            "content_hash",
        ],
    ),
    (
        "blueprints",
        &[
            "exam",
            "subject",
            "level",
            "topic",
            "section",
            "members",
            "paper_size",
            "pct",
            "pct_low",
            "pct_high",
            "expected",
            "expected_low",
            "expected_high",
            "source",
            "sample",
            "method",
            "confidence",
            "status",
            "note",
        ],
    ),
];

/// Create every production table we read. Idempotent; safe to run at boot.
pub async fn ensure_schema(s: &DbState) -> Result<(), AppError> {
    for ddl in DDL {
        super::write::execute_ddl_local(s, ddl).await?;
    }
    apply_migrations(s).await?;
    for index in INDEXES {
        super::write::execute_ddl_local(s, index).await?;
    }
    Ok(())
}

/// API-owned migrations are numbered, applied once, and never rewritten.
/// Fresh databases receive the current DDL first; upgraded databases receive
/// the same DDL idempotently and then any missing migrations.
const MIGRATIONS: &[u64] = &[
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
];

async fn apply_migrations(s: &DbState) -> Result<(), AppError> {
    for &version in MIGRATIONS {
        let applied = with_conn(s, |conn| async move {
            let mut rows = conn
                .query(
                    "SELECT 1 FROM api_schema_migrations WHERE version = ?1",
                    [version as i64],
                )
                .await
                .map_err(upstream)?;
            Ok(rows.next().await.map_err(upstream)?.is_some())
        })
        .await?;
        if applied {
            continue;
        }

        // These versions belonged to the removed notes/textbook content
        // model. Keep their migration numbers acknowledged for existing
        // replicas, but do not recreate deleted tables on a fresh database.
        if matches!(version, 3 | 4 | 8..=12) {
            super::write::execute_write_local(
                s,
                "INSERT INTO api_schema_migrations (version) VALUES (?1)",
                vec![turso::Value::Integer(version as i64)],
            )
            .await?;
            continue;
        }

        match version {
            1 => {
                migrate_reports_to_targets(s).await?;
                ensure_column(
                    s,
                    "dashboard_users",
                    "role",
                    "role TEXT NOT NULL DEFAULT 'customer'",
                )
                .await?;
                ensure_column(s, "api_keys", "owner", "owner TEXT NOT NULL DEFAULT ''").await?;
            }
            2 => {
                ensure_column(s, "api_keys", "idempotency_hash", "idempotency_hash TEXT").await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_idempotency_hash ON api_keys(idempotency_hash)",
                )
                .await?;
            }
            3 => {
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS topic_notes (id TEXT PRIMARY KEY, exam TEXT NOT NULL, subject TEXT NOT NULL, topic_slug TEXT NOT NULL, subtopic_slug TEXT, title TEXT NOT NULL, read_time_minutes INTEGER NOT NULL, key_takeaway TEXT NOT NULL, sections TEXT NOT NULL, worked_examples TEXT NOT NULL DEFAULT '[]', formulas TEXT NOT NULL DEFAULT '[]', active_recall_checks TEXT NOT NULL DEFAULT '[]', examiner_traps TEXT NOT NULL DEFAULT '[]', sources TEXT NOT NULL DEFAULT '[]', linked_question_ids TEXT NOT NULL DEFAULT '[]', content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_notes_lookup ON topic_notes (exam, subject, topic_slug)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_notes_subtopic_lookup ON topic_notes (exam, subject, subtopic_slug)",
                )
                .await?;
            }
            4 => {
                // Collapse duplicate placements before the unique indexes
                // exist. Keep the most recently inserted row in each group.
                super::write::execute_write_local(
                    s,
                    r#"DELETE FROM topic_notes
                       WHERE (subtopic_slug IS NULL OR subtopic_slug = '')
                         AND rowid NOT IN (
                           SELECT MAX(rowid) FROM topic_notes
                           WHERE subtopic_slug IS NULL OR subtopic_slug = ''
                           GROUP BY exam, subject, topic_slug
                         )"#,
                    vec![],
                )
                .await?;
                super::write::execute_write_local(
                    s,
                    r#"DELETE FROM topic_notes
                       WHERE subtopic_slug IS NOT NULL AND subtopic_slug <> ''
                         AND rowid NOT IN (
                           SELECT MAX(rowid) FROM topic_notes
                           WHERE subtopic_slug IS NOT NULL AND subtopic_slug <> ''
                           GROUP BY exam, subject, subtopic_slug
                         )"#,
                    vec![],
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_unique_topic ON topic_notes (exam, subject, topic_slug) WHERE subtopic_slug IS NULL OR subtopic_slug = ''",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_unique_subtopic ON topic_notes (exam, subject, subtopic_slug) WHERE subtopic_slug IS NOT NULL AND subtopic_slug <> ''",
                )
                .await?;
            }
            5 => {
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS theory_questions (id TEXT PRIMARY KEY, exam TEXT NOT NULL, subject TEXT NOT NULL, year INTEGER NOT NULL, paper INTEGER NOT NULL DEFAULT 2, section TEXT NOT NULL, question_number TEXT NOT NULL, topic_slug TEXT NOT NULL, subtopic_slug TEXT, total_marks INTEGER NOT NULL, stem TEXT NOT NULL, diagram_url TEXT, sub_parts TEXT NOT NULL DEFAULT '[]', formulation_bridge TEXT NOT NULL DEFAULT '[]', marking_methods TEXT NOT NULL DEFAULT '[]', diagram_rubric TEXT, penalties TEXT NOT NULL DEFAULT '[]', examiner_report TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_theory_lookup ON theory_questions (exam, subject, topic_slug)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_theory_year_lookup ON theory_questions (exam, subject, year)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_theory_unique ON theory_questions (exam, subject, year, question_number)",
                )
                .await?;
            }
            6 => {
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS api_access_tokens (token_hash TEXT PRIMARY KEY, parent_prefix TEXT NOT NULL, scopes TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_access_tokens_parent ON api_access_tokens(parent_prefix)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_access_tokens_expiry ON api_access_tokens(expires_at)",
                )
                .await?;
            }
            7 => {
                // Migration 5 shipped the index without `paper`. A database
                // that already recorded version 5 keeps that older index, so
                // replace it explicitly instead of relying on `IF NOT EXISTS`.
                super::write::execute_ddl_local(s, "DROP INDEX IF EXISTS idx_theory_unique")
                    .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_theory_unique ON theory_questions (exam, subject, year, paper, question_number)",
                )
                .await?;
            }
            8 => {
                ensure_column(
                    s,
                    "topic_notes",
                    "sources",
                    "sources TEXT NOT NULL DEFAULT '[]'",
                )
                .await?;
            }
            9 => {
                // The textbook layer. A book owns the teaching, so none of
                // these tables names an exam. The exam layer points at them.
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS books (id TEXT PRIMARY KEY, title TEXT NOT NULL, subject_area TEXT NOT NULL, level TEXT NOT NULL, edition TEXT NOT NULL DEFAULT 'draft-1', description TEXT NOT NULL DEFAULT '', parts TEXT NOT NULL DEFAULT '[]', sources TEXT NOT NULL DEFAULT '[]', content_hash TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS chapters (chapter_id TEXT PRIMARY KEY, book_id TEXT NOT NULL, part_id TEXT, order_index INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL, schema_version INTEGER NOT NULL DEFAULT 2, updated_at TEXT NOT NULL, facts_inherited INTEGER NOT NULL DEFAULT 0, learning_objectives TEXT NOT NULL DEFAULT '[]', prerequisites TEXT NOT NULL DEFAULT '[]', formula_sheet TEXT NOT NULL DEFAULT '[]', glossary TEXT NOT NULL DEFAULT '[]', sources TEXT NOT NULL DEFAULT '[]', content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters (book_id, title)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS chapter_sections (id TEXT PRIMARY KEY, chapter_id TEXT NOT NULL, order_index INTEGER NOT NULL, slug TEXT NOT NULL, title TEXT NOT NULL, est_minutes INTEGER NOT NULL DEFAULT 0, facts_inherited INTEGER NOT NULL DEFAULT 0, learning_objectives TEXT NOT NULL DEFAULT '[]', teaching_text TEXT NOT NULL DEFAULT '{\"blocks\":[]}', worked_examples TEXT NOT NULL DEFAULT '[]', misconceptions TEXT NOT NULL DEFAULT '[]', summary_points TEXT NOT NULL DEFAULT '[]', exam_links TEXT NOT NULL DEFAULT '[]', provenance TEXT NOT NULL DEFAULT '{}', no_worked_example_reason TEXT, content_hash TEXT NOT NULL, study_checks TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_chapter_sections_chapter ON chapter_sections (chapter_id, order_index)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS chapter_exercises (id TEXT PRIMARY KEY, chapter_id TEXT NOT NULL, section_id TEXT NOT NULL, tier TEXT NOT NULL, kind TEXT NOT NULL, difficulty INTEGER NOT NULL, marks REAL NOT NULL, stem TEXT NOT NULL, options TEXT NOT NULL DEFAULT '[]', answer TEXT NOT NULL, answer_kind TEXT NOT NULL, solution TEXT NOT NULL DEFAULT '[]', hints TEXT NOT NULL DEFAULT '[]', tags TEXT NOT NULL DEFAULT '[]', provenance TEXT NOT NULL DEFAULT '{}', solution_provenance TEXT NOT NULL DEFAULT '', answer_note TEXT, content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_chapter_exercises_section ON chapter_exercises (section_id, tier)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS exam_traps (id TEXT PRIMARY KEY, chapter_id TEXT NOT NULL, exam TEXT NOT NULL, subject TEXT NOT NULL, section_id TEXT NOT NULL, misconception TEXT NOT NULL, correction TEXT NOT NULL, signal TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'candidate', paper_evidence TEXT NOT NULL DEFAULT '{}', frequency TEXT NOT NULL DEFAULT 'candidate', provenance TEXT NOT NULL DEFAULT '{}', content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_exam_traps_exam ON exam_traps (exam, subject)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS exam_recall_checks (id TEXT PRIMARY KEY, chapter_id TEXT NOT NULL, exam TEXT NOT NULL, subject TEXT NOT NULL, section_id TEXT NOT NULL, stem TEXT NOT NULL, options TEXT NOT NULL DEFAULT '[]', answer TEXT NOT NULL, explanation TEXT NOT NULL, difficulty INTEGER NOT NULL DEFAULT 2, source TEXT NOT NULL DEFAULT '', content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_exam_recall_checks_exam ON exam_recall_checks (exam, subject)",
                )
                .await?;
            }
            10 => {
                // Chapters carry the book's reading order. The column is
                // added separately because migration 9 may already have
                // created the table without it.
                ensure_column(
                    s,
                    "chapters",
                    "order_index",
                    "order_index INTEGER NOT NULL DEFAULT 0",
                )
                .await?;
                super::write::execute_ddl_local(s, "DROP INDEX IF EXISTS idx_chapters_book")
                    .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters (book_id, order_index)",
                )
                .await?;
            }
            11 => {
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_chapter_exercises_chapter ON chapter_exercises (chapter_id)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_exam_traps_chapter ON exam_traps (chapter_id, section_id)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE INDEX IF NOT EXISTS idx_exam_recall_checks_chapter ON exam_recall_checks (chapter_id, section_id)",
                )
                .await?;
            }
            12 => {
                ensure_column(
                    s,
                    "chapter_sections",
                    "study_checks",
                    "study_checks TEXT NOT NULL DEFAULT '[]'",
                )
                .await?;
            }
            13 => {
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS lessons (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '{}', subject TEXT NOT NULL, level TEXT NOT NULL DEFAULT '', estimated_minutes INTEGER NOT NULL DEFAULT 0, objectives TEXT NOT NULL DEFAULT '[]', content TEXT NOT NULL DEFAULT '[]', checks TEXT NOT NULL DEFAULT '[]', misconceptions TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '[]', provenance TEXT NOT NULL DEFAULT '{}', content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS topic_lessons (exam TEXT NOT NULL, subject TEXT NOT NULL, topic_slug TEXT NOT NULL, lesson_id TEXT NOT NULL, order_index INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (exam, subject, topic_slug, lesson_id))",
                )
                .await?;
            }
            14 => {
                ensure_column(
                    s,
                    "lessons",
                    "version",
                    "version INTEGER NOT NULL DEFAULT 1",
                )
                .await?;
                ensure_column(
                    s,
                    "lessons",
                    "status",
                    "status TEXT NOT NULL DEFAULT 'published'",
                )
                .await?;
                ensure_column(
                    s,
                    "topic_lessons",
                    "subtopic_slug",
                    "subtopic_slug TEXT NOT NULL DEFAULT ''",
                )
                .await?;
                super::write::execute_ddl_local(
                    s,
                    "CREATE TABLE IF NOT EXISTS lesson_revisions (lesson_id TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, subject TEXT NOT NULL, level TEXT NOT NULL, estimated_minutes INTEGER NOT NULL, objectives TEXT NOT NULL, content TEXT NOT NULL, checks TEXT NOT NULL, misconceptions TEXT NOT NULL, summary TEXT NOT NULL, provenance TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (lesson_id, version))",
                ).await?;
            }
            15 => {
                // Rebuild the relationship table so upgraded databases get
                // the same subtopic-aware key as fresh databases.
                for index in ["idx_topic_lessons_topic", "idx_topic_lessons_lesson"] {
                    super::write::execute_ddl_local(s, &format!("DROP INDEX IF EXISTS {index}"))
                        .await?;
                }
                super::write::execute_ddl_local(s, "CREATE TABLE topic_lessons_v15 (exam TEXT NOT NULL, subject TEXT NOT NULL, topic_slug TEXT NOT NULL, subtopic_slug TEXT NOT NULL DEFAULT '', lesson_id TEXT NOT NULL, order_index INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (exam, subject, topic_slug, subtopic_slug, lesson_id))").await?;
                super::write::execute_write_local(s, "INSERT OR IGNORE INTO topic_lessons_v15 (exam, subject, topic_slug, subtopic_slug, lesson_id, order_index) SELECT exam, subject, topic_slug, COALESCE(subtopic_slug, ''), lesson_id, order_index FROM topic_lessons", vec![]).await?;
                super::write::execute_ddl_local(s, "DROP TABLE topic_lessons").await?;
                super::write::execute_ddl_local(
                    s,
                    "ALTER TABLE topic_lessons_v15 RENAME TO topic_lessons",
                )
                .await?;
                for table in [
                    "books",
                    "chapters",
                    "chapter_sections",
                    "chapter_exercises",
                    "exam_traps",
                    "exam_recall_checks",
                    "topic_notes",
                ] {
                    super::write::execute_ddl_local(s, &format!("DROP TABLE IF EXISTS {table}"))
                        .await?;
                }
            }
            16 => {
                super::write::execute_ddl_local(s, "CREATE TABLE IF NOT EXISTS lesson_example_questions (lesson_id TEXT NOT NULL, question_id TEXT NOT NULL, order_index INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (lesson_id, question_id))").await?;
                let old_exists = with_conn(s, |conn| async move {
                    let mut rows = conn.query("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lesson_questions'", ()).await.map_err(upstream)?;
                    Ok(rows.next().await.map_err(upstream)?.is_some())
                }).await?;
                if old_exists {
                    super::write::execute_ddl_local(
                        s,
                        "DROP INDEX IF EXISTS idx_lesson_questions_lesson",
                    )
                    .await?;
                    super::write::execute_ddl_local(
                        s,
                        "DROP INDEX IF EXISTS idx_lesson_questions_question",
                    )
                    .await?;
                    super::write::execute_write_local(s, "INSERT OR IGNORE INTO lesson_example_questions (lesson_id, question_id, order_index) SELECT lesson_id, question_id, order_index FROM lesson_questions", vec![]).await?;
                    super::write::execute_ddl_local(s, "DROP TABLE lesson_questions").await?;
                }
                super::write::execute_ddl_local(s, "CREATE INDEX IF NOT EXISTS idx_lesson_example_questions_lesson ON lesson_example_questions (lesson_id, order_index)").await?;
            }
            17 => {
                let has_topics = with_conn(s, |conn| async move {
                    let mut rows = conn
                        .query(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='topics'",
                            (),
                        )
                        .await
                        .map_err(upstream)?;
                    Ok(rows.next().await.map_err(upstream)?.is_some())
                })
                .await?;
                let has_subtopics = with_conn(s, |conn| async move {
                    let mut rows = conn
                        .query(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='subtopics'",
                            (),
                        )
                        .await
                        .map_err(upstream)?;
                    Ok(rows.next().await.map_err(upstream)?.is_some())
                })
                .await?;
                let has_questions = with_conn(s, |conn| async move {
                    let mut rows = conn
                        .query(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='questions'",
                            (),
                        )
                        .await
                        .map_err(upstream)?;
                    Ok(rows.next().await.map_err(upstream)?.is_some())
                })
                .await?;
                if has_topics {
                    ensure_column(
                        s,
                        "topics",
                        "lesson_refs",
                        "lesson_refs TEXT NOT NULL DEFAULT '[]'",
                    )
                    .await?;
                }
                if has_subtopics {
                    ensure_column(
                        s,
                        "subtopics",
                        "lesson_refs",
                        "lesson_refs TEXT NOT NULL DEFAULT '[]'",
                    )
                    .await?;
                }
                super::write::execute_ddl_local(s, "CREATE TABLE lessons_v17 (id TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'published', title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '{}', subject TEXT NOT NULL, level TEXT NOT NULL DEFAULT '', estimated_minutes INTEGER NOT NULL DEFAULT 0, objectives TEXT NOT NULL DEFAULT '[]', content TEXT NOT NULL DEFAULT '[]', checks TEXT NOT NULL DEFAULT '[]', misconceptions TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '[]', example_question_refs TEXT NOT NULL DEFAULT '[]', provenance TEXT NOT NULL DEFAULT '{}', content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (id, version))").await?;
                if has_questions {
                    super::write::execute_write_local(s, "INSERT INTO lessons_v17 (id, version, status, title, description, subject, level, estimated_minutes, objectives, content, checks, misconceptions, summary, example_question_refs, provenance, content_hash, created_at, updated_at) SELECT l.id, l.version, l.status, l.title, l.description, l.subject, l.level, l.estimated_minutes, l.objectives, l.content, l.checks, l.misconceptions, l.summary, COALESCE((SELECT json_group_array(json_object('id', q.id, 'title', substr(q.text, 1, 120))) FROM lesson_example_questions leq JOIN questions q ON q.id=leq.question_id WHERE leq.lesson_id=l.id), '[]'), l.provenance, l.content_hash, l.created_at, l.updated_at FROM lessons l", vec![]).await?;
                } else {
                    super::write::execute_write_local(s, "INSERT INTO lessons_v17 (id, version, status, title, description, subject, level, estimated_minutes, objectives, content, checks, misconceptions, summary, example_question_refs, provenance, content_hash, created_at, updated_at) SELECT id, version, status, title, description, subject, level, estimated_minutes, objectives, content, checks, misconceptions, summary, '[]', provenance, content_hash, created_at, updated_at FROM lessons", vec![]).await?;
                }
                super::write::execute_write_local(s, "INSERT OR IGNORE INTO lessons_v17 (id, version, status, title, description, subject, level, estimated_minutes, objectives, content, checks, misconceptions, summary, example_question_refs, provenance, content_hash, created_at, updated_at) SELECT lesson_id, version, status, title, description, subject, level, estimated_minutes, objectives, content, checks, misconceptions, summary, '[]', provenance, content_hash, created_at, created_at FROM lesson_revisions", vec![]).await?;
                if has_topics {
                    super::write::execute_write_local(s, "UPDATE topics SET lesson_refs=COALESCE((SELECT json_group_array(json_object('id',tl.lesson_id,'title',(SELECT title FROM lessons WHERE id=tl.lesson_id ORDER BY version DESC LIMIT 1))) FROM topic_lessons tl WHERE tl.exam=topics.exam AND tl.subject=topics.subject AND tl.topic_slug=topics.slug),'[]')", vec![]).await?;
                }
                if has_subtopics {
                    super::write::execute_write_local(s, "UPDATE subtopics SET lesson_refs=COALESCE((SELECT json_group_array(json_object('id',tl.lesson_id,'title',(SELECT title FROM lessons WHERE id=tl.lesson_id ORDER BY version DESC LIMIT 1))) FROM topic_lessons tl WHERE tl.topic_slug=subtopics.topic AND tl.subtopic_slug=subtopics.slug),'[]')", vec![]).await?;
                }
                super::write::execute_ddl_local(s, "DROP TABLE lessons").await?;
                super::write::execute_ddl_local(s, "ALTER TABLE lessons_v17 RENAME TO lessons")
                    .await?;
                for table in [
                    "lesson_revisions",
                    "lesson_example_questions",
                    "topic_lessons",
                ] {
                    super::write::execute_ddl_local(s, &format!("DROP TABLE IF EXISTS {table}"))
                        .await?;
                }
            }
            18 => {
                // Lessons are current-by-id, like the other content surfaces.
                // Keep the latest published row when upgrading the temporary
                // revisioned shape, then remove the revision columns/tables.
                super::write::execute_ddl_local(s, "CREATE TABLE lessons_v18 (id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'published', title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '{}', subject TEXT NOT NULL, level TEXT NOT NULL DEFAULT '', estimated_minutes INTEGER NOT NULL DEFAULT 0, objectives TEXT NOT NULL DEFAULT '[]', content TEXT NOT NULL DEFAULT '[]', checks TEXT NOT NULL DEFAULT '[]', misconceptions TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '[]', example_question_refs TEXT NOT NULL DEFAULT '[]', provenance TEXT NOT NULL DEFAULT '{}', content_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)").await?;
                super::write::execute_write_local(s, "INSERT INTO lessons_v18 (id, status, title, description, subject, level, estimated_minutes, objectives, content, checks, misconceptions, summary, example_question_refs, provenance, content_hash, created_at, updated_at) SELECT id, status, title, description, subject, level, estimated_minutes, objectives, content, checks, misconceptions, summary, example_question_refs, provenance, content_hash, created_at, updated_at FROM lessons l WHERE version=(SELECT MAX(version) FROM lessons latest WHERE latest.id=l.id)", vec![]).await?;
                super::write::execute_ddl_local(s, "DROP TABLE lessons").await?;
                super::write::execute_ddl_local(s, "ALTER TABLE lessons_v18 RENAME TO lessons")
                    .await?;
                super::write::execute_ddl_local(s, "DROP TABLE IF EXISTS lesson_revisions").await?;
            }
            19 => {
                // The exam-owned JSON refs now carry the relationship and its
                // order. Fold any remaining rows into them before dropping the
                // table, so an older replica does not lose authored links.
                super::lessons::backfill_lesson_refs(s).await?;
                super::write::execute_ddl_local(s, "DROP TABLE IF EXISTS topic_lessons").await?;
            }

            _ => {
                return Err(AppError::Internal(
                    "unsupported schema migration".to_string(),
                ));
            }
        }

        super::write::execute_write_local(
            s,
            "INSERT INTO api_schema_migrations (version) VALUES (?1)",
            vec![turso::Value::Integer(version as i64)],
        )
        .await?;
    }
    Ok(())
}

/// The `reports` table first shipped question-only (`question_id` plus a
/// `UNIQUE(question_id, …)`). Returns its row count when that legacy
/// shape is present, or `None` when the table is absent or already
/// target-agnostic: a pure read, so it probes safely on every boot.
async fn legacy_reports_rows(s: &DbState) -> Result<Option<i64>, AppError> {
    with_conn(s, |conn| async move {
        let mut cols = Vec::new();
        let mut rows = conn
            .query("PRAGMA table_info(reports)", ())
            .await
            .map_err(upstream)?;
        while let Some(row) = rows.next().await.map_err(upstream)? {
            cols.push(row.get::<String>(1).map_err(upstream)?);
        }
        if cols.is_empty() || !cols.iter().any(|c| c == "question_id") {
            return Ok(None);
        }
        let mut rows = conn
            .query("SELECT COUNT(*) FROM reports", ())
            .await
            .map_err(upstream)?;
        let n: i64 = rows
            .next()
            .await
            .map_err(upstream)?
            .and_then(|r| r.get(0).ok())
            .unwrap_or(0);
        Ok(Some(n))
    })
    .await
}

/// Rebuild the legacy question-only `reports` table to the target-agnostic
/// shape. Only safe while empty: rows are real filings, and dropping them
/// would be silent data loss, so that fails loudly instead of guessing.
async fn migrate_reports_to_targets(s: &DbState) -> Result<(), AppError> {
    match legacy_reports_rows(s).await? {
        None => Ok(()),
        Some(0) => super::write::execute_ddl_local(s, "DROP TABLE reports").await,
        Some(n) => Err(AppError::Upstream(format!(
            "reports table holds {n} legacy-shape rows; refusing to drop them"
        ))),
    }
}

/// Bring one table to the contract shape. SQLite has no IF NOT EXISTS
/// for columns: probe first, ALTER once, ignore the already-there error.
pub(crate) async fn ensure_column(
    s: &DbState,
    table: &str,
    column: &str,
    ddl: &str,
) -> Result<(), AppError> {
    let has: bool = with_conn(s, |conn| async move {
        let mut rows = conn
            .query(format!("PRAGMA table_info({table})"), ())
            .await
            .map_err(upstream)?;
        while let Some(row) = rows.next().await.map_err(upstream)? {
            let name: String = row.get(1).map_err(upstream)?;
            if name == column {
                return Ok(true);
            }
        }
        Ok(false)
    })
    .await?;
    if !has {
        super::write::execute_ddl_local(s, &format!("ALTER TABLE {table} ADD COLUMN {ddl}"))
            .await?;
    }
    Ok(())
}

/// The first way the replica departs from the shapes this binary reads, or
/// `None` when every table and column in `READ_SHAPES` is present. Reads
/// only, so it runs on every boot and every re-check.
pub async fn check_shapes(s: &DbState) -> Result<Option<String>, AppError> {
    for (table, columns) in READ_SHAPES {
        let present: Vec<String> = with_conn(s, |conn| {
            let table = table.to_string();
            async move {
                let mut rows = conn
                    .query(format!("PRAGMA table_info(\"{table}\")"), ())
                    .await
                    .map_err(upstream)?;
                let mut cols = Vec::new();
                while let Some(row) = rows.next().await.map_err(upstream)? {
                    cols.push(row.get::<String>(1).map_err(upstream)?);
                }
                Ok(cols)
            }
        })
        .await?;
        if present.is_empty() {
            return Ok(Some(format!("table {table} is missing")));
        }
        for col in *columns {
            if !present.iter().any(|c| c == col) {
                return Ok(Some(format!("table {table} is missing column {col}")));
            }
        }
    }
    Ok(None)
}

/// Fold both guards into one answer: `None` when the replica matches this
/// binary, or the reason it does not. Reads the stamped version, stamping
/// ours when absent, then checks the shapes we read.
pub async fn check_contract(s: &DbState) -> Result<Option<String>, AppError> {
    let current: Option<String> = with_conn(s, |conn| async move {
        let mut rows = conn
            .query("SELECT value FROM meta WHERE key='contract_version'", ())
            .await
            .map_err(upstream)?;
        Ok(rows
            .next()
            .await
            .map_err(upstream)?
            .and_then(|r| r.get(0).ok()))
    })
    .await?;
    match current {
        None => {
            super::write::execute_write_local(
                s,
                "INSERT INTO meta (key, value) VALUES ('contract_version', ?1)",
                vec![turso::Value::Text(CONTRACT_VERSION.to_string())],
            )
            .await?;
        }
        Some(v) if v.trim() != CONTRACT_VERSION.to_string() => {
            return Ok(Some(format!(
                "contract version {} != {}",
                v.trim(),
                CONTRACT_VERSION
            )));
        }
        Some(_) => {}
    }
    check_shapes(s).await
}

/// Resolve the passive bank version from the meta table or fallback to the contract version.
pub async fn read_bank_version(s: &DbState) -> String {
    let val: Option<String> = with_conn(s, |conn| async move {
        let mut rows = conn
            .query(
                "SELECT value FROM meta WHERE key IN ('bank_version', 'contract_version') ORDER BY CASE WHEN key='bank_version' THEN 0 ELSE 1 END LIMIT 1",
                (),
            )
            .await
            .map_err(upstream)?;
        Ok(rows
            .next()
            .await
            .map_err(upstream)?
            .and_then(|r| r.get(0).ok()))
    })
    .await
    .unwrap_or(None);

    match val {
        Some(v) if !v.trim().is_empty() => {
            let trimmed = v.trim();
            if trimmed.starts_with('v') {
                trimmed.to_string()
            } else {
                format!("v{trimmed}")
            }
        }
        _ => format!("v{}", CONTRACT_VERSION),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::{api_schema, bank_schema, conn_of, db_state, replica};

    async fn local_db() -> crate::state::DbState {
        db_state(replica().await)
    }

    /// Startup schema work is local. An unreachable remote must not keep the
    /// process from serving reads: every DDL and migration lands, each failed
    /// push is handed to the supervisor, and only a request write surfaces the
    /// failure to the caller.
    #[tokio::test]
    async fn startup_schema_completes_while_the_remote_is_unreachable() {
        let s = local_db().await;
        ensure_schema(&s)
            .await
            .expect("schema work must not depend on a successful push");

        let conn = conn_of(&s).await;
        let mut rows = conn
            .query("SELECT COUNT(*) FROM api_schema_migrations", ())
            .await
            .expect("migration table");
        let count: i64 = rows
            .next()
            .await
            .expect("next")
            .and_then(|r| r.get(0).ok())
            .expect("count");
        assert_eq!(
            count,
            MIGRATIONS.len() as i64,
            "every migration must be recorded locally"
        );

        let mut rows = conn
            .query(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='api_keys'",
                (),
            )
            .await
            .expect("sqlite_master");
        assert!(
            rows.next().await.expect("next").is_some(),
            "the schema must be present even when the cloud is not"
        );

        // The contrast: a request write is not startup work, so the same
        // the cloud push remains pending.
        let accepted = crate::store::write::execute_write(
            &s,
            "INSERT INTO meta (key, value) VALUES ('probe', 'v')",
            vec![],
        )
        .await;
        assert!(accepted.is_ok(), "a request write is accepted locally");
    }

    #[tokio::test]
    async fn fresh_api_schema_has_no_topic_lessons_table() {
        let s = local_db().await;
        ensure_schema(&s).await.expect("schema work");
        let conn = conn_of(&s).await;
        let mut rows = conn
            .query(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='topic_lessons'",
                (),
            )
            .await
            .expect("sqlite_master");
        assert!(
            rows.next().await.expect("next").is_none(),
            "the relationship table must not survive a fresh schema"
        );
    }

    #[tokio::test]
    async fn migration_nineteen_folds_relationship_rows_into_json_refs() {
        let s = local_db().await;
        let conn = conn_of(&s).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["topics", "subtopics"]).await;
        for version in 1..=18 {
            conn.execute(
                "INSERT INTO api_schema_migrations (version) VALUES (?1)",
                [version as i64],
            )
            .await
            .expect("record applied migration");
        }
        conn.execute(
            "CREATE TABLE topic_lessons (exam TEXT, subject TEXT, topic_slug TEXT, subtopic_slug TEXT NOT NULL DEFAULT '', lesson_id TEXT, order_index INTEGER NOT NULL DEFAULT 0)",
            (),
        )
        .await
        .expect("relationship table");
        conn.execute(
            "INSERT INTO lessons (id,status,title,description,subject,level,estimated_minutes,objectives,content,checks,misconceptions,summary,example_question_refs,provenance,content_hash) VALUES ('lesson:english:first','published','First lesson','{}','english-language','secondary',5,'[]','[]','[]','[]','[]','[]','{}','hash')",
            (),
        )
        .await
        .expect("lesson");
        conn.execute(
            "INSERT INTO topics VALUES ('comprehension','english-language','JAMB','Comprehension',1,0,'[]','[]','[]')",
            (),
        )
        .await
        .expect("topic");
        conn.execute(
            "INSERT INTO subtopics VALUES ('comprehension','comprehension','Comprehension',1,'[]','[]')",
            (),
        )
        .await
        .expect("subtopic");
        for subtopic in ["", "comprehension"] {
            conn.execute(
                "INSERT INTO topic_lessons VALUES ('JAMB','english-language','comprehension',?1,'lesson:english:first',1)",
                [subtopic],
            )
            .await
            .expect("relationship row");
        }

        apply_migrations(&s).await.expect("migration nineteen");

        let mut rows = conn
            .query(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='topic_lessons'",
                (),
            )
            .await
            .expect("sqlite_master");
        assert!(rows.next().await.expect("next").is_none(), "table dropped");

        for sql in [
            "SELECT lesson_refs FROM topics WHERE slug='comprehension'",
            "SELECT lesson_refs FROM subtopics WHERE slug='comprehension'",
        ] {
            let mut rows = conn.query(sql, ()).await.expect("refs query");
            let raw: String = rows
                .next()
                .await
                .expect("row")
                .expect("result")
                .get(0)
                .expect("json");
            let refs: Vec<crate::core::models::ContentReference> =
                serde_json::from_str(&raw).expect("refs json");
            assert_eq!(refs.len(), 1);
            assert_eq!(refs[0].id, "lesson:english:first");
            assert_eq!(refs[0].title, "First lesson");
            assert_eq!(refs[0].order, 1);
        }
    }

    #[tokio::test]
    async fn absent_table_has_no_legacy_shape() {
        let s = local_db().await;
        assert_eq!(legacy_reports_rows(&s).await.expect("probe"), None);
    }

    #[tokio::test]
    async fn current_shape_is_not_legacy() {
        let s = local_db().await;
        conn_of(&s)
            .await
            .execute(
                "CREATE TABLE reports (id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL, reporter TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT, created_at INTEGER NOT NULL, UNIQUE(reporter, target_type, target_id, reason))",
                (),
            )
            .await
            .expect("ddl");
        assert_eq!(legacy_reports_rows(&s).await.expect("probe"), None);
    }

    #[tokio::test]
    async fn legacy_empty_detected_for_rebuild() {
        let s = local_db().await;
        conn_of(&s)
            .await
            .execute(
                "CREATE TABLE reports (id TEXT PRIMARY KEY, question_id TEXT NOT NULL, reporter TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT, created_at INTEGER NOT NULL, UNIQUE(reporter, question_id, reason))",
                (),
            )
            .await
            .expect("legacy ddl");
        assert_eq!(legacy_reports_rows(&s).await.expect("probe"), Some(0));
    }

    #[tokio::test]
    async fn legacy_populated_reports_count() {
        let s = local_db().await;
        let conn = conn_of(&s).await;
        conn.execute(
            "CREATE TABLE reports (id TEXT PRIMARY KEY, question_id TEXT NOT NULL, reporter TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT, created_at INTEGER NOT NULL, UNIQUE(reporter, question_id, reason))",
            (),
        )
        .await
        .expect("legacy ddl");
        conn.execute(
            "INSERT INTO reports VALUES ('r1','q1','k1','other',NULL,1)",
            (),
        )
        .await
        .expect("legacy row");
        assert_eq!(legacy_reports_rows(&s).await.expect("probe"), Some(1));
    }

    async fn create(conn: &turso::Connection, table: &str, columns: &[&str]) {
        let cols = if columns.is_empty() {
            String::from("\"c\" INTEGER")
        } else {
            columns
                .iter()
                .map(|c| format!("\"{c}\" TEXT"))
                .collect::<Vec<_>>()
                .join(",")
        };
        conn.execute(&format!("CREATE TABLE \"{table}\" ({cols})"), ())
            .await
            .expect("ddl");
    }

    #[tokio::test]
    async fn declared_shapes_pass_when_present() {
        let s = local_db().await;
        let conn = conn_of(&s).await;
        for (table, columns) in READ_SHAPES {
            create(&conn, table, columns).await;
        }
        assert_eq!(check_shapes(&s).await.expect("probe"), None);
    }

    #[tokio::test]
    async fn missing_table_is_named() {
        let s = local_db().await;
        assert_eq!(
            check_shapes(&s).await.expect("probe"),
            Some(String::from("table meta is missing"))
        );
    }

    #[tokio::test]
    async fn missing_column_is_named() {
        let s = local_db().await;
        let conn = conn_of(&s).await;
        for (table, columns) in READ_SHAPES {
            let cols: Vec<&str> = if *table == "questions" {
                columns
                    .iter()
                    .copied()
                    .filter(|c| *c != "content_hash")
                    .collect()
            } else {
                columns.to_vec()
            };
            create(&conn, table, &cols).await;
        }
        assert_eq!(
            check_shapes(&s).await.expect("probe"),
            Some(String::from(
                "table questions is missing column content_hash"
            ))
        );
    }

    #[test]
    fn every_owned_table_has_a_declared_shape() {
        for ddl in DDL {
            let name = ddl
                .strip_prefix("CREATE TABLE IF NOT EXISTS ")
                .and_then(|rest| rest.split_whitespace().next())
                .expect("ddl names its table");
            assert!(
                READ_SHAPES.iter().any(|(t, _)| *t == name),
                "{name} is created by DDL but has no READ_SHAPES entry"
            );
        }
    }

    #[test]
    fn every_introspectable_table_has_a_declared_shape() {
        for table in crate::core::catalog::INTROSPECTABLE_TABLES {
            assert!(
                READ_SHAPES.iter().any(|(t, _)| t == table),
                "{table} is introspectable but has no READ_SHAPES entry"
            );
        }
    }

    #[test]
    fn api_migrations_are_numbered_and_reach_the_declared_version() {
        assert!(!MIGRATIONS.is_empty());
        assert!(MIGRATIONS.windows(2).all(|pair| pair[0] < pair[1]));
        assert_eq!(MIGRATIONS.last().copied(), Some(API_SCHEMA_VERSION));
    }

    #[cfg(any())]
    #[tokio::test]
    async fn migration_twelve_adds_study_checks_to_existing_sections() {
        let s = local_db().await;
        {
            let conn = conn_of(&s).await;
            conn.execute(
                "CREATE TABLE api_schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                (),
            )
            .await
            .expect("migration table");
            conn.execute("CREATE TABLE chapter_sections (id TEXT PRIMARY KEY)", ())
                .await
                .expect("old section table");
            for version in 1..=11 {
                conn.execute(
                    "INSERT INTO api_schema_migrations (version) VALUES (?1)",
                    [version],
                )
                .await
                .expect("previous migration");
            }
        }

        apply_migrations(&s).await.expect("apply migration 12");
        let conn = conn_of(&s).await;
        let mut rows = conn
            .query("PRAGMA table_info(chapter_sections)", ())
            .await
            .expect("section shape");
        let mut found = false;
        while let Some(row) = rows.next().await.expect("next column") {
            let name: String = row.get(1).expect("column name");
            if name == "study_checks" {
                found = true;
                break;
            }
        }
        assert!(found, "migration 12 must add study_checks");
    }

    #[cfg(any())]
    async fn insert_note(
        conn: &turso::Connection,
        id: &str,
        subtopic: Option<&str>,
    ) -> Result<u64, turso::Error> {
        conn.execute(
            "INSERT INTO topic_notes (id, exam, subject, topic_slug, subtopic_slug, title, read_time_minutes, key_takeaway, sections, worked_examples, formulas, active_recall_checks, examiner_traps, linked_question_ids, content_hash) \
             VALUES (?1, 'JAMB', 'physics', 'motion', ?2, 'T', 3, '{\"text\":\"x\",\"inline\":[]}', '[]', '[]', '[]', '[]', '[]', '[]', 'h')",
            vec![
                turso::Value::Text(id.to_string()),
                subtopic
                    .map(|slug| turso::Value::Text(slug.to_string()))
                    .unwrap_or(turso::Value::Null),
            ],
        )
        .await
    }

    #[cfg(any())]
    #[tokio::test]
    async fn duplicate_note_placements_are_rejected_by_the_unique_indexes() {
        let s = local_db().await;
        let conn = conn_of(&s).await;
        crate::testing::api_schema(&conn).await;

        insert_note(&conn, "n1", None)
            .await
            .expect("first topic note");
        assert!(
            insert_note(&conn, "n2", None).await.is_err(),
            "a second topic note for the same placement must be rejected"
        );

        insert_note(&conn, "s1", Some("projectiles"))
            .await
            .expect("first subtopic note");
        assert!(
            insert_note(&conn, "s2", Some("projectiles")).await.is_err(),
            "a second subtopic note for the same placement must be rejected"
        );
    }

    #[tokio::test]
    async fn duplicate_theory_questions_are_rejected_by_the_unique_index() {
        let s = local_db().await;
        let conn = conn_of(&s).await;
        crate::testing::api_schema(&conn).await;

        let insert = |id: &'static str| {
            let conn = &conn;
            async move {
                conn.execute(
                    "INSERT INTO theory_questions (id, exam, subject, year, paper, section, question_number, topic_slug, subtopic_slug, total_marks, stem, diagram_url, sub_parts, formulation_bridge, marking_methods, diagram_rubric, penalties, examiner_report, content_hash) \
                     VALUES (?1, 'WAEC', 'general-mathematics', 2023, 2, 'Section A', '4', 'algebra', null, 8, '{\"text\":\"s\",\"inline\":[]}', null, '[]', '[]', '[]', null, '[]', '{\"general_performance\":\"g\",\"common_errors\":[],\"remedies\":\"r\"}', 'hash')",
                    vec![turso::Value::Text(id.to_string())],
                )
                .await
            }
        };

        insert("q1").await.expect("first question");
        assert!(
            insert("q2").await.is_err(),
            "a second question for the same exam, subject, year, paper, and question_number must be rejected"
        );

        // Different paper in the same year and question_number is allowed
        conn.execute(
            "INSERT INTO theory_questions (id, exam, subject, year, paper, section, question_number, topic_slug, subtopic_slug, total_marks, stem, diagram_url, sub_parts, formulation_bridge, marking_methods, diagram_rubric, penalties, examiner_report, content_hash) \
             VALUES ('q3', 'WAEC', 'general-mathematics', 2023, 3, 'Section A', '4', 'algebra', null, 8, '{\"text\":\"s\",\"inline\":[]}', null, '[]', '[]', '[]', null, '[]', '{\"general_performance\":\"g\",\"common_errors\":[],\"remedies\":\"r\"}', 'hash')",
            (),
        )
        .await
        .expect("paper 3 question with same number must be allowed");
    }

    #[tokio::test]
    async fn migration_seven_replaces_the_legacy_theory_unique_index() {
        let s = local_db().await;
        let conn = conn_of(&s).await;
        crate::testing::api_schema(&conn).await;

        // A database that already recorded versions 1-6 still carries the
        // original four-column index, because `IF NOT EXISTS` matches it by
        // name. Migration 7 has to replace it rather than skip it.
        conn.execute("DROP INDEX idx_theory_unique", ())
            .await
            .expect("drop current index");
        conn.execute(
            "CREATE UNIQUE INDEX idx_theory_unique ON theory_questions (exam, subject, year, question_number)",
            (),
        )
        .await
        .expect("legacy index");
        for version in 1..=6 {
            conn.execute(
                "INSERT INTO api_schema_migrations (version) VALUES (?1)",
                vec![turso::Value::Integer(version)],
            )
            .await
            .expect("record migration");
        }

        ensure_schema(&s).await.expect("upgrade");

        let mut rows = conn
            .query("PRAGMA index_info('idx_theory_unique')", ())
            .await
            .expect("index info");
        let mut columns = Vec::new();
        while let Some(row) = rows.next().await.expect("index row") {
            columns.push(row.get::<String>(2).expect("column name"));
        }
        assert_eq!(
            columns,
            ["exam", "subject", "year", "paper", "question_number"],
            "the upgraded index must include paper"
        );
    }

    async fn owned_shape(conn: &turso::Connection) -> Vec<(String, Vec<String>)> {
        let mut shape = Vec::new();
        for ddl in DDL {
            let table = ddl
                .strip_prefix("CREATE TABLE IF NOT EXISTS ")
                .and_then(|rest| rest.split_whitespace().next())
                .expect("ddl names its table");
            let mut rows = conn
                .query(format!("PRAGMA table_info(\"{table}\")"), ())
                .await
                .expect("table info");
            let mut columns = Vec::new();
            while let Some(row) = rows.next().await.expect("table info row") {
                columns.push(row.get::<String>(1).expect("column name"));
            }
            columns.sort();
            shape.push((table.to_string(), columns));
        }
        shape
    }

    #[tokio::test]
    async fn fresh_and_upgraded_api_shapes_converge() {
        let fresh = local_db().await;
        let fresh_conn = conn_of(&fresh).await;
        for ddl in DDL {
            fresh_conn.execute(ddl, ()).await.expect("fresh ddl");
        }
        let fresh_shape = owned_shape(&fresh_conn).await;

        let upgraded = local_db().await;
        let upgraded_conn = conn_of(&upgraded).await;
        upgraded_conn
            .execute(
                "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                (),
            )
            .await
            .expect("legacy meta");
        upgraded_conn
            .execute(
                "CREATE TABLE api_keys (prefix TEXT PRIMARY KEY, hash TEXT NOT NULL, tier TEXT NOT NULL, scopes TEXT NOT NULL, revoked INTEGER NOT NULL, created_at TEXT NOT NULL)",
                (),
            )
            .await
            .expect("legacy keys");
        upgraded_conn
            .execute(
                "CREATE TABLE dashboard_users (username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, created_at TEXT NOT NULL)",
                (),
            )
            .await
            .expect("legacy users");
        upgraded_conn
            .execute(
                "CREATE TABLE reports (id TEXT PRIMARY KEY, question_id TEXT NOT NULL, reporter TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT, created_at INTEGER NOT NULL, UNIQUE(reporter, question_id, reason))",
                (),
            )
            .await
            .expect("legacy reports");

        for ddl in DDL {
            upgraded_conn.execute(ddl, ()).await.expect("upgrade ddl");
        }
        upgraded_conn
            .execute("DROP TABLE reports", ())
            .await
            .expect("replace legacy reports");
        let reports_ddl = DDL
            .iter()
            .find(|ddl| ddl.starts_with("CREATE TABLE IF NOT EXISTS reports "))
            .expect("the reports table is declared");
        upgraded_conn
            .execute(reports_ddl, ())
            .await
            .expect("current reports");
        upgraded_conn
            .execute(
                "ALTER TABLE dashboard_users ADD COLUMN role TEXT NOT NULL DEFAULT 'customer'",
                (),
            )
            .await
            .expect("migrate user role");
        upgraded_conn
            .execute(
                "ALTER TABLE api_keys ADD COLUMN owner TEXT NOT NULL DEFAULT ''",
                (),
            )
            .await
            .expect("migrate key owner");
        upgraded_conn
            .execute("ALTER TABLE api_keys ADD COLUMN idempotency_hash TEXT", ())
            .await
            .expect("migrate key idempotency hash");
        upgraded_conn
            .execute("INSERT INTO api_schema_migrations (version) VALUES (1)", ())
            .await
            .expect("record migration");

        assert_eq!(owned_shape(&upgraded_conn).await, fresh_shape);
    }
}
