//! Sole owner of every database touchpoint.
//!
//! Laws (see foundation contract):
//! - This module tree is the only importer of `turso` in the crate.
//! - Every query passes [`gate`]; saturation answers 503, never queues.
//! - Raw SQL lives only in `catalog`/`accounts`, always parameterized or
//!   validated through [`crate::core::validate::ident`].
//! - Transient lock contention retries inside these walls; consumers see
//!   [`crate::error::AppError`] only.

pub mod accounts;
pub mod catalog;
pub mod schema;
pub mod sync;
pub mod write;

use std::{future::Future, sync::Arc};

use tokio::sync::{Mutex, OwnedSemaphorePermit, Semaphore};

use crate::{error::AppError, state::DbState};

pub type SyncDb = Arc<turso::sync::Database>;
pub type DbGate = Arc<Semaphore>;

const RETRIES: u32 = 5;

/// A pool of long-lived connections, sized to the DB gate.
///
/// `Database::connect()` is a sync-engine operation: it is driven through the
/// engine's single IO worker, the same worker the background pull runs on.
/// Opening a connection per query therefore queues behind whatever that worker
/// is doing, and serializes every request in the meantime. Reusing connections
/// keeps reads on the local file and off the worker entirely. Capacity matches
/// the gate, so a permit always finds an idle connection.
pub struct ConnPool {
    idle: Mutex<Vec<turso::Connection>>,
    capacity: usize,
}

impl ConnPool {
    pub fn new(capacity: usize) -> Self {
        Self {
            idle: Mutex::new(Vec::with_capacity(capacity)),
            capacity,
        }
    }

    /// Open connections up to capacity. Called at boot, before the pull loop
    /// starts, while the IO worker is still free.
    pub(crate) async fn fill(&self, db: &SyncDb) {
        for _ in 0..self.capacity {
            match db.connect().await {
                Ok(conn) => self.put(conn).await,
                Err(e) => {
                    tracing::warn!("connection pool fill stopped: {e}");
                    return;
                }
            }
        }
    }

    /// Take an idle connection. Opening one here only happens for one-shot
    /// commands or if the boot fill came up short; it is cheap then because no
    /// pull is in flight.
    async fn take(&self, db: &SyncDb) -> Result<turso::Connection, AppError> {
        let idle = self.idle.lock().await.pop();
        match idle {
            Some(conn) => Ok(conn),
            None => db.connect().await.map_err(upstream),
        }
    }

    /// Return a connection for reuse, never growing past capacity.
    async fn put(&self, conn: turso::Connection) {
        let mut idle = self.idle.lock().await;
        if idle.len() < self.capacity {
            idle.push(conn);
        }
    }
}

fn gate(s: &DbState) -> Result<OwnedSemaphorePermit, AppError> {
    s.db_gate.clone().try_acquire_owned().map_err(|_| {
        s.metrics
            .gate_rejections
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        AppError::DbSaturated
    })
}

/// Whether an error text looks like transient contention worth retrying.
/// [`upstream`] erases the `turso::Error` variant before this sees it, so the
/// match is on text: `busy`/`locked` cover `Busy`/`BusySnapshot` ("database is
/// busy"), and `conflict` is the sync engine's commit-time wording, which a
/// string-only match would otherwise miss.
fn is_busy(e: &AppError) -> bool {
    match e {
        AppError::Upstream(m) => {
            let m = m.to_ascii_lowercase();
            m.contains("locked") || m.contains("busy") || m.contains("conflict")
        }
        _ => false,
    }
}

async fn backoff(attempt: u32) {
    tokio::time::sleep(std::time::Duration::from_millis(100 * attempt as u64)).await;
}

/// Map any displayable engine error into the shared upstream variant.
/// This is the only spelling for that conversion in the crate.
pub(crate) fn upstream<E: std::fmt::Display>(e: E) -> AppError {
    AppError::Upstream(e.to_string())
}

async fn synced(s: &DbState) -> Result<SyncDb, AppError> {
    s.db.read()
        .await
        .clone()
        .ok_or(AppError::DbUnavailable("sync"))
}

/// Single entry point for gated local reads: acquire the gate, then take a
/// pooled connection and run `op` on it, returning it to the pool when done.
/// The connection is reused across busy retries. Anything that only reads
/// goes through here, so bursts degrade to 503 on exhaustion instead of
/// wedging workers. (Writes use `write::{execute_write, execute_ddl}` — same
/// gate, plus the write mutex and cloud push.)
pub(crate) async fn with_conn<T, F, Fut>(s: &DbState, mut op: F) -> Result<T, AppError>
where
    F: FnMut(turso::Connection) -> Fut,
    Fut: Future<Output = Result<T, AppError>>,
{
    let _permit = gate(s)?;
    let mut attempt = 0;
    loop {
        let db = synced(s).await?;
        let conn = s.conns.take(&db).await?;
        let outcome = op(conn.clone()).await;
        s.conns.put(conn).await;
        match outcome {
            Ok(v) => return Ok(v),
            Err(e) if !is_busy(&e) => return Err(e),
            Err(_) if attempt >= RETRIES => return Err(AppError::DbSaturated),
            Err(_) => {
                attempt += 1;
                backoff(attempt).await;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state_with_permits(n: usize) -> DbState {
        DbState {
            db: Arc::new(tokio::sync::RwLock::new(None)),
            db_gate: Arc::new(Semaphore::new(n)),
            conns: Arc::new(ConnPool::new(n)),
            metrics: Arc::new(crate::state::Metrics::default()),
            cookie_secure: false,
            write_mutex: Arc::new(tokio::sync::Mutex::new(())),
            contract_ok: Arc::new(std::sync::atomic::AtomicBool::new(true)),
            limiter: Arc::new(crate::auth::rate_limit::RateLimiter::new()),
        }
    }

    #[tokio::test]
    async fn gate_admits_up_to_limit_then_saturates() {
        let s = state_with_permits(2);
        let _a = gate(&s).expect("first permit");
        let _b = gate(&s).expect("second permit");
        assert!(matches!(gate(&s), Err(AppError::DbSaturated)));
        assert_eq!(
            s.metrics
                .gate_rejections
                .load(std::sync::atomic::Ordering::Relaxed),
            1
        );
    }

    #[tokio::test]
    async fn missing_db_reports_unavailable() {
        let s = state_with_permits(4);
        assert!(matches!(synced(&s).await, Err(AppError::DbUnavailable(_))));
    }
}
