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
//! `DDL` creates the tables the API owns. The bank tables (questions,
//! subjects, passages, …) are owned and created by the pipeline, so the
//! API never creates them: they are declared here as reads, not DDL.

use super::{upstream, with_conn};
use crate::{error::AppError, state::DbState};

/// Bump when a production shape changes. The pipeline stamps what it
/// promoted against; anything else fails the version half of the check.
pub const CONTRACT_VERSION: u64 = 1;

/// Tables the API owns and creates at boot.
const DDL: &[&str] = &[
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS api_keys (prefix TEXT PRIMARY KEY, hash TEXT NOT NULL, tier TEXT NOT NULL DEFAULT 'commercial', scopes TEXT NOT NULL DEFAULT 'read:catalog', revoked INTEGER NOT NULL DEFAULT 0, owner TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS dashboard_users (username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'customer', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL, reporter TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT, created_at INTEGER NOT NULL, UNIQUE(reporter, target_type, target_id, reason))",
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
            "is_compulsory",
            "objective_paper_questions",
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
        ],
    ),
    (
        "subtopics",
        &["slug", "topic", "name", "order", "objectives"],
    ),
    ("topic_countries", &["topic", "country"]),
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
    // Shape migrations run before the DDL so a dropped table is recreated
    // at the current shape by the loop below.
    migrate_reports_to_targets(s).await?;
    for ddl in DDL {
        super::write::execute_ddl(s, ddl).await?;
    }
    Ok(())
}

/// The `reports` table first shipped question-only (`question_id` plus a
/// `UNIQUE(question_id, …)`). Returns its row count when that legacy
/// shape is present, or `None` when the table is absent or already
/// target-agnostic — a pure read, so it probes safely on every boot.
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
        Some(0) => super::write::execute_ddl(s, "DROP TABLE reports").await,
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
        super::write::execute_ddl(s, &format!("ALTER TABLE {table} ADD COLUMN {ddl}")).await?;
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
            super::write::execute_write(
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

#[cfg(test)]
mod tests {
    use super::*;

    async fn local_db() -> crate::state::DbState {
        let path = std::env::temp_dir().join(format!(
            "utmelab-schema-test-{}-{}.db",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        let db = turso::sync::Builder::new_remote(path.to_str().expect("tmp path"))
            .with_remote_url("http://127.0.0.1:9")
            .with_auth_token("test-only")
            .bootstrap_if_empty(false)
            .build()
            .await
            .expect("local sync db builds offline");
        crate::state::DbState::detached(std::sync::Arc::new(db))
    }

    #[tokio::test]
    async fn absent_table_has_no_legacy_shape() {
        let s = local_db().await;
        assert_eq!(legacy_reports_rows(&s).await.expect("probe"), None);
    }

    #[tokio::test]
    async fn current_shape_is_not_legacy() {
        let s = local_db().await;
        s.db.read()
            .await
            .clone()
            .expect("db")
            .connect()
            .await
            .expect("connect")
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
        s.db.read()
            .await
            .clone()
            .expect("db")
            .connect()
            .await
            .expect("connect")
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
        let conn =
            s.db.read()
                .await
                .clone()
                .expect("db")
                .connect()
                .await
                .expect("connect");
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

    async fn open(s: &crate::state::DbState) -> turso::Connection {
        s.db.read()
            .await
            .clone()
            .expect("db")
            .connect()
            .await
            .expect("connect")
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
        let conn = open(&s).await;
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
        let conn = open(&s).await;
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
}
