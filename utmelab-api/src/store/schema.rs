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
];

/// Create every production table we read. Idempotent; safe to run at boot.
pub async fn ensure_schema(s: &DbState) -> Result<(), AppError> {
    for ddl in DDL {
        super::write::execute_ddl(s, ddl).await?;
    }
    Ok(())
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
