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

use tokio::sync::{OwnedSemaphorePermit, Semaphore};

use crate::{error::AppError, state::DbState};

pub type SyncDb = Arc<turso::sync::Database>;
pub type DbGate = Arc<Semaphore>;

const RETRIES: u32 = 5;

fn gate(s: &DbState) -> Result<OwnedSemaphorePermit, AppError> {
    s.db_gate.clone().try_acquire_owned().map_err(|_| {
        s.metrics
            .gate_rejections
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        AppError::DbSaturated
    })
}

fn is_busy(e: &AppError) -> bool {
    match e {
        AppError::Upstream(m) => {
            let m = m.to_ascii_lowercase();
            m.contains("locked") || m.contains("busy")
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

/// Single entry point for gated local reads: acquire the gate, then
/// connect inside the busy-retry loop and run `op` (which receives a
/// fresh connection per attempt). Anything that only reads goes through
/// here, so bursts degrade to 503 on exhaustion instead of wedging
/// workers. (Writes use `write::{execute_write, execute_ddl}` — same
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
        let conn = db.connect().await.map_err(upstream)?;
        match op(conn).await {
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
