//! The single source of Turso in this process (Phase 0).
//!
//! One `Db` is built at boot from `TURSO_DB_URL + TURSO_DB_TOKEN`, runs every
//! file in `migrations/` in order, and is then borrowed by every store.
//! Feature modules (`keys/`, later `bank/`) own their tables and SQL but
//! never touch `Builder`, env vars or DDL — that all lives here.
//!
//! `Connection` is cheaply cloneable (clones share the stream, statements run
//! one at a time in order), so handing one per store is a handle copy, not a
//! new TCP session.

use turso_serverless::{Builder, Connection};

use crate::error::ApiError;

/// Ordered migrations. Each file runs once via `execute_batch`, which applies
/// multi-statement SQL in order. Keep this list sorted — filenames are the
/// version.
const MIGRATIONS: &[(&str, &str)] = &[(
    "0001_api_keys.sql",
    include_str!("../../migrations/0001_api_keys.sql"),
)];

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
    /// Connect to the remote database. No statements run here — use
    /// [`Db::migrate`] once at boot.
    pub async fn connect(url: &str, token: &str) -> Result<Self, ApiError> {
        let database = Builder::new_remote(url)
            .with_auth_token(token)
            .build()
            .await
            .map_err(|e| internal("build", e))?;
        let conn = database
            .connect()
            .map_err(|e| internal("connect", e))?;
        Ok(Self { conn })
    }

    /// Run every file in `migrations/` in order. Idempotent: every DDL uses
    /// `IF NOT EXISTS`, so a restart re-applies safely.
    pub async fn migrate(&self) -> Result<(), ApiError> {
        for (name, sql) in MIGRATIONS {
            self.conn
                .execute_batch(sql)
                .await
                .map_err(|e| internal(name, e))?;
        }
        Ok(())
    }

    /// A handle for a feature store. Cheap clone of the shared stream.
    pub fn conn(&self) -> Connection {
        self.conn.clone()
    }
}
