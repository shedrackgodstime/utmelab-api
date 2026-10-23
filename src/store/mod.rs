//! Sole owner of every database touchpoint.
//!
//! Laws (see foundation contract):
//! - This module tree is the only importer of `turso` in the crate.
//! - Every query passes the `gate`; saturation answers 503, never queues.
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

/// Whether an error is transient contention worth retrying. The classification
/// happens once, in [`upstream`], where the typed engine error is still in
/// hand; this only reads that decision back, so no retry path guesses from text.
fn is_busy(e: &AppError) -> bool {
    matches!(e, AppError::DbContended)
}

async fn backoff(attempt: u32) {
    tokio::time::sleep(std::time::Duration::from_millis(100 * attempt as u64)).await;
}

/// Map any engine error into the shared variants. This is the only spelling
/// for that conversion in the crate.
///
/// Contention is classified here: `Busy`/`BusySnapshot` carry it typed, and the
/// sync engine and the remote report some of it as a plain message, so that
/// wording is matched here too: once, beside the typed match, on engine errors
/// only, and nowhere else. Everything else keeps its text as [`AppError::Upstream`].
pub(crate) fn upstream<E: std::error::Error + 'static>(e: E) -> AppError {
    if is_contention(&e) {
        AppError::DbContended
    } else {
        AppError::Upstream(e.to_string())
    }
}

/// Contention is only meaningful for an engine error; a serde or IO error is
/// never retryable, so its text is not consulted.
fn is_contention(e: &(dyn std::error::Error + 'static)) -> bool {
    let Some(err) = e.downcast_ref::<turso::Error>() else {
        return false;
    };
    match err {
        turso::Error::Busy(_) | turso::Error::BusySnapshot(_) => true,
        // The sync engine and the remote report some contention as a plain
        // message, which the variant cannot carry.
        turso::Error::Error(m) => {
            let m = m.to_ascii_lowercase();
            m.contains("busy") || m.contains("locked") || m.contains("conflict")
        }
        _ => false,
    }
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
/// wedging workers. (Writes use `write::{execute_write, execute_ddl}`, with the same
/// gate, plus the write mutex and cloud push.)
pub(crate) async fn with_conn<T, F, Fut>(s: &DbState, mut op: F) -> Result<T, AppError>
where
    F: FnMut(turso::Connection) -> Fut,
    Fut: Future<Output = Result<T, AppError>>,
{
    let mut attempt = 0;
    loop {
        let outcome = {
            let _permit = gate(s)?;
            let db = synced(s).await?;
            let conn = s.conns.take(&db).await?;
            let outcome = op(conn.clone()).await;
            s.conns.put(conn).await;
            outcome
        };
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
    use crate::testing::{db_state, db_state_without_db, replica};
    use std::sync::Arc;

    #[tokio::test]
    async fn gate_admits_up_to_limit_then_saturates() {
        let s = db_state_without_db(true, 2);
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
    async fn retry_backoff_releases_the_gate_permit() {
        let mut s = db_state(replica().await);
        s.db_gate = Arc::new(Semaphore::new(1));
        s.conns = Arc::new(ConnPool::new(1));
        let gate_ref = Arc::clone(&s.db_gate);

        let (first_attempt_sender, first_attempt_done) = tokio::sync::oneshot::channel();
        let mut first_attempt = Some(first_attempt_sender);
        let task = tokio::spawn(async move {
            with_conn(&s, move |_conn| {
                let is_first = first_attempt.is_some();
                if is_first {
                    first_attempt
                        .take()
                        .expect("first attempt signal sender")
                        .send(())
                        .expect("signal first attempt");
                }
                async move {
                    if is_first {
                        Err(AppError::DbContended)
                    } else {
                        Ok(())
                    }
                }
            })
            .await
        });

        first_attempt_done.await.expect("receive first attempt");
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        let permit = gate_ref.try_acquire_owned();
        assert!(permit.is_ok(), "retry backoff must release the gate permit");
        drop(permit);

        task.await
            .expect("retry task joins")
            .expect("second attempt succeeds");
    }

    #[tokio::test]
    async fn missing_db_reports_unavailable() {
        let s = db_state_without_db(true, 4);
        assert!(matches!(synced(&s).await, Err(AppError::DbUnavailable(_))));
    }

    #[test]
    fn upstream_classifies_engine_contention_by_variant() {
        assert!(matches!(
            upstream(turso::Error::Busy("database is busy".to_string())),
            AppError::DbContended
        ));
        assert!(matches!(
            upstream(turso::Error::BusySnapshot("snapshot busy".to_string())),
            AppError::DbContended
        ));
        // The sync engine and the remote report contention as a plain message.
        assert!(matches!(
            upstream(turso::Error::Error("Database is busy".to_string())),
            AppError::DbContended
        ));
        // A non-engine error is never contention, even if its text says so.
        let io = std::io::Error::other("lock conflict");
        assert!(matches!(upstream(io), AppError::Upstream(_)));
        // An engine error that is not contention keeps its text.
        assert!(matches!(
            upstream(turso::Error::Error("no such table: x".to_string())),
            AppError::Upstream(_)
        ));
    }

    #[test]
    fn is_busy_reads_the_typed_decision_not_the_text() {
        assert!(is_busy(&AppError::DbContended));
        assert!(!is_busy(&AppError::Upstream(
            "database is busy".to_string()
        )));
    }
}
