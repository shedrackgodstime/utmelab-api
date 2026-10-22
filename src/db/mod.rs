//! The single source of Turso in this process (Phase 0 scaffolding).
//!
//! One `Db` is built from `TURSO_DB_URL + TURSO_DB_TOKEN` and borrowed by
//! every store. Feature modules (`keys/`, later `bank/`) own their tables and
//! SQL but never touch `Builder` or env vars.
//!
//! No migrations run yet — nothing moves until its phase lands. `Db` is only
//! a shared connection handle plus the read-only `audit-db` checker, so the
//! scaffolding can be proven without migrating anything.
//!
//! `Connection` is cheaply cloneable (clones share the stream, statements run
//! one at a time in order), so handing one per store is a handle copy, not a
//! new TCP session.

use turso_serverless::{Builder, Connection};

use crate::error::ApiError;

mod audit;

pub use audit::{AuditReport, TableAudit, run as audit};

fn internal(context: &str, e: impl std::fmt::Display) -> ApiError {
    ApiError::Internal(format!("db {context}: {e}"))
}

/// The shared Turso handle. Cloneable: every store holds its own `Connection`
/// cloned from the same `Database`.
#[derive(Clone, Debug)]
pub struct Db {
    conn: Connection,
}

impl Db {
    /// Connect to the remote database. Runs no statements — stores own their
    /// DDL until their migration phase lands.
    pub async fn connect(url: &str, token: &str) -> Result<Self, ApiError> {
        let database = Builder::new_remote(url)
            .with_auth_token(token)
            .build()
            .await
            .map_err(|e| internal("build", e))?;
        let conn = database.connect().map_err(|e| internal("connect", e))?;
        Ok(Self { conn })
    }

    /// A handle for a feature store. Cheap clone of the shared stream.
    pub fn conn(&self) -> Connection {
        self.conn.clone()
    }
}
