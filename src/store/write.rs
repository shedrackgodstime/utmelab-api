//! Single write path. Execute under the write mutex, record the local change,
//! then wake the one background push worker. The pull loop and push worker
//! still serialize database synchronization, but request latency no longer
//! includes the Turso push.

use super::{
    gate,
    sync::{admit_write, unix_now, Engine, ErrorClass, SyncEvent, WriteDecision, WriteRejection},
    synced, upstream,
};
use crate::{error::AppError, state::DbState};

fn push_error(error: super::sync::SyncError) -> AppError {
    match error.class {
        ErrorClass::Contention => AppError::DbContended,
        _ => AppError::Upstream(error.message),
    }
}

fn estimated_bytes(sql: &str, params: &[turso::Value]) -> u64 {
    // This is an admission estimate, not an accounting record. It keeps a
    // large outbound statement from looking like empty pending work.
    (sql.len() as u64).saturating_add((params.len() as u64).saturating_mul(32))
}

fn ensure_write_admitted(s: &DbState) -> Result<(), AppError> {
    if s.sync.stop_requested() {
        return Err(AppError::DbUnavailable("sync"));
    }
    match admit_write(s.sync.pending_work(), &s.sync.policy().write_admission) {
        WriteDecision::Admit => Ok(()),
        WriteDecision::Reject(reason) => {
            tracing::warn!(
                event = "write_admission_rejected",
                reason = match reason {
                    WriteRejection::PendingOperationBudget => "pending_operations",
                    WriteRejection::PendingByteBudget => "pending_bytes",
                },
                pending_operations = s.sync.health().pending_operations,
                pending_bytes = s.sync.health().pending_bytes,
                "write admission rejected"
            );
            Err(AppError::DbSaturated)
        }
    }
}

fn record_push_result(
    s: &DbState,
    result: &Result<(), super::sync::SyncError>,
) -> Result<(), AppError> {
    match result {
        Ok(()) => {
            s.sync.apply(SyncEvent::PushSucceeded { at: unix_now() });
            Ok(())
        }
        Err(error) => {
            s.sync.apply(SyncEvent::PushFailed {
                error: error.clone(),
                at: unix_now(),
            });
            s.push_notify.notify_one();
            Err(push_error(error.clone()))
        }
    }
}

fn queue_push(s: &DbState) {
    s.push_notify.notify_one();
}

fn record_write_wait(s: &DbState, elapsed: std::time::Duration) {
    use std::sync::atomic::Ordering::Relaxed;
    let ms = elapsed.as_millis().min(u64::MAX as u128) as u64;
    if ms == 0 {
        return;
    }
    s.metrics.write_wait_count.fetch_add(1, Relaxed);
    s.metrics.write_wait_ms_total.fetch_add(ms, Relaxed);
    let max = &s.metrics.write_wait_ms_max;
    let mut current = max.load(Relaxed);
    while ms > current {
        match max.compare_exchange_weak(current, ms, Relaxed, Relaxed) {
            Ok(_) => break,
            Err(actual) => current = actual,
        }
    }
}

fn record_local_write(s: &DbState, started: std::time::Instant) {
    use std::sync::atomic::Ordering::Relaxed;
    let ms = started.elapsed().as_millis().min(u64::MAX as u128) as u64;
    s.metrics.local_write_count.fetch_add(1, Relaxed);
    s.metrics.local_write_ms_total.fetch_add(ms, Relaxed);
    let max = &s.metrics.local_write_ms_max;
    let mut current = max.load(Relaxed);
    while ms > current {
        match max.compare_exchange_weak(current, ms, Relaxed, Relaxed) {
            Ok(_) => break,
            Err(actual) => current = actual,
        }
    }
}

pub async fn execute_write(
    s: &DbState,
    sql: &str,
    params: Vec<turso::Value>,
) -> Result<u64, AppError> {
    let _permit = gate(s)?;
    let wait_started = std::time::Instant::now();
    let _w = s.write_mutex.lock().await;
    record_write_wait(s, wait_started.elapsed());
    ensure_write_admitted(s)?;
    let db = synced(s).await?;
    let conn = s.conns.take(&db, s.sync.policy().budgets).await?;
    let estimated = estimated_bytes(sql, &params);
    let local_started = std::time::Instant::now();
    let result = execute_and_verify(&conn, sql, params).await;
    s.conns.put(conn).await;
    record_local_write(s, local_started);
    let n = result?;
    if n > 0 {
        s.sync.mark_write_committed(n, estimated);
        queue_push(s);
    }
    Ok(n)
}

/// DDL twin of [`execute_write`]. `changes()` is meaningless for schema
/// statements, so no visibility check: failure still surfaces as Err.
pub async fn execute_ddl(s: &DbState, sql: &str) -> Result<(), AppError> {
    let _permit = gate(s)?;
    let wait_started = std::time::Instant::now();
    let _w = s.write_mutex.lock().await;
    record_write_wait(s, wait_started.elapsed());
    ensure_write_admitted(s)?;
    let db = synced(s).await?;
    let conn = s.conns.take(&db, s.sync.policy().budgets).await?;
    let estimated = estimated_bytes(sql, &[] as &[turso::Value]);
    let local_started = std::time::Instant::now();
    let result = conn.execute(sql, ()).await.map_err(upstream);
    s.conns.put(conn).await;
    record_local_write(s, local_started);
    result?;
    s.sync.mark_write_committed(1, estimated);
    queue_push(s);
    Ok(())
}

/// Startup DDL. The local schema is the read path's contract, so a push
/// failure is recorded for the push supervisor instead of blocking
/// convergence. A read-only token can then boot and serve reads while writes
/// keep reporting their own failure.
pub async fn execute_ddl_local(s: &DbState, sql: &str) -> Result<(), AppError> {
    let _permit = gate(s)?;
    let wait_started = std::time::Instant::now();
    let _w = s.write_mutex.lock().await;
    record_write_wait(s, wait_started.elapsed());
    ensure_write_admitted(s)?;
    let db = synced(s).await?;
    let conn = s.conns.take(&db, s.sync.policy().budgets).await?;
    let estimated = estimated_bytes(sql, &[] as &[turso::Value]);
    let result = conn.execute(sql, ()).await.map_err(upstream);
    s.conns.put(conn).await;
    result?;
    s.sync.mark_write_committed(1, estimated);
    s.sync.apply(SyncEvent::PushStarted { at: unix_now() });
    if let Err(error) = Engine::new(db, s.sync.policy().budgets).push().await {
        tracing::debug!(class = error.class.as_str(), "startup DDL push pending");
        let _ = record_push_result(s, &Err(error));
    } else {
        s.sync.apply(SyncEvent::PushSucceeded { at: unix_now() });
    }
    Ok(())
}

/// Startup data work, same contract as [`execute_ddl_local`].
pub async fn execute_write_local(
    s: &DbState,
    sql: &str,
    params: Vec<turso::Value>,
) -> Result<u64, AppError> {
    let _permit = gate(s)?;
    let wait_started = std::time::Instant::now();
    let _w = s.write_mutex.lock().await;
    record_write_wait(s, wait_started.elapsed());
    ensure_write_admitted(s)?;
    let db = synced(s).await?;
    let conn = s.conns.take(&db, s.sync.policy().budgets).await?;
    let estimated = estimated_bytes(sql, &params);
    let result = execute_and_verify(&conn, sql, params).await;
    s.conns.put(conn).await;
    let n = result?;
    if n > 0 {
        s.sync.mark_write_committed(n, estimated);
    }
    s.sync.apply(SyncEvent::PushStarted { at: unix_now() });
    if let Err(error) = Engine::new(db, s.sync.policy().budgets).push().await {
        tracing::debug!(class = error.class.as_str(), "startup write push pending");
        let _ = record_push_result(s, &Err(error));
    } else {
        s.sync.apply(SyncEvent::PushSucceeded { at: unix_now() });
    }
    Ok(n)
}

/// Execute then confirm the row count is visible on the same connection.
async fn execute_and_verify(
    conn: &turso::Connection,
    sql: &str,
    params: Vec<turso::Value>,
) -> Result<u64, AppError> {
    let n = conn.execute(sql, params).await.map_err(upstream)?;
    let seen: i64 = conn
        .query("SELECT changes()", ())
        .await
        .map_err(upstream)?
        .next()
        .await
        .map_err(upstream)?
        .and_then(|r| r.get(0).ok())
        .unwrap_or(0);
    if seen != n as i64 {
        return Err(AppError::Upstream("write not visible".to_string()));
    }
    Ok(n)
}

#[cfg(test)]
mod tests {
    use crate::testing::{api_schema, conn_of, connect, db_state, replica};

    /// The local write succeeds without waiting for the unreachable remote.
    #[tokio::test]
    async fn a_write_lands_locally_without_waiting_for_push() {
        let db = replica().await;
        api_schema(&connect(&db).await).await;
        let s = db_state(db);

        let result = super::execute_write(
            &s,
            "INSERT INTO meta (key, value) VALUES ('k', 'v')",
            vec![],
        )
        .await;
        assert!(
            result.is_ok(),
            "local commit should not wait for cloud push"
        );

        // The row is committed locally all the same.
        let conn = conn_of(&s).await;
        let mut rows = conn
            .query("SELECT value FROM meta WHERE key='k'", ())
            .await
            .expect("query");
        let row = rows.next().await.expect("next").expect("row");
        assert_eq!(row.get::<String>(0).expect("value"), "v");
    }

    #[tokio::test]
    async fn pending_work_marks_the_write_and_then_blocks_new_writes_at_the_budget() {
        use crate::store::sync::{SyncPolicy, SyncStatus};
        use std::sync::Arc;

        let db = replica().await;
        api_schema(&connect(&db).await).await;
        let mut policy = SyncPolicy::default();
        policy.write_admission.max_pending_operations = 1;
        policy.write_admission.max_pending_bytes = 1024;
        let mut s = db_state(db);
        s.sync = Arc::new(SyncStatus::verified(policy));

        let result = super::execute_write(
            &s,
            "INSERT INTO meta (key, value) VALUES ('k', 'v')",
            vec![],
        )
        .await;
        assert!(result.is_ok(), "the local commit should be accepted");
        let health = s.sync.health();
        assert!(health.push_pending);
        assert_eq!(health.pending_operations, 1);

        let blocked = super::execute_write(
            &s,
            "INSERT INTO meta (key, value) VALUES ('k2', 'v2')",
            vec![],
        )
        .await;
        assert!(
            blocked.is_err(),
            "the pending budget must refuse the next write before it reaches the local store"
        );

        let conn = conn_of(&s).await;
        let mut rows = conn
            .query("SELECT COUNT(*) FROM meta WHERE key='k2'", ())
            .await
            .expect("query");
        let count: i64 = rows
            .next()
            .await
            .expect("next")
            .and_then(|r| r.get(0).ok())
            .expect("count");
        assert_eq!(count, 0, "the refused write must not reach the local store");
    }
}
