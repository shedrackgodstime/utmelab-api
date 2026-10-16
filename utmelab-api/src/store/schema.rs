//! Single source of truth for production shapes.
//!
//! The pipeline stages whatever it wants in its own database, but what
//! lands in the production database must match this file: table DDL plus
//! a `contract_version` handshake. Drift cannot go silent — a version the
//! server does not know fails loudly instead of serving misshapen rows.
//!
//! Domain tables (questions, subjects, passages, …) join this module when
//! bank data lands, each with a contract bump. Auth tables are here now
//! because they already exist in production.

use super::{upstream, with_conn};
use crate::{error::AppError, state::DbState};

/// Bump when a production shape changes. The pipeline stamps what it
/// promoted against; anything else fails the check below.
pub const CONTRACT_VERSION: u64 = 1;

const DDL: &[&str] = &[
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS api_keys (prefix TEXT PRIMARY KEY, hash TEXT NOT NULL, tier TEXT NOT NULL DEFAULT 'commercial', scopes TEXT NOT NULL DEFAULT 'read:catalog', revoked INTEGER NOT NULL DEFAULT 0, owner TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS dashboard_users (username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'customer', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL, reporter TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT, created_at INTEGER NOT NULL, UNIQUE(reporter, target_type, target_id, reason))",
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

/// Read the stamped version, stamping ours when absent.
/// Returns true when the replica matches this binary.
pub async fn check_version(s: &DbState) -> Result<bool, AppError> {
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
            Ok(true)
        }
        Some(v) => Ok(v.trim() == CONTRACT_VERSION.to_string()),
    }
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
}
