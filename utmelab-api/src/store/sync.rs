//! Replica lifecycle. Builds the synced database in the background so
//! serving never blocks on it, fills the connection pool while the engine's IO
//! worker is still free, then re-pulls on an interval. We deliberately do not
//! long-poll: a pull in flight occupies that worker, and `connect()`/`push()`
//! on the serving path would queue behind it. Pull failures back off and
//! retry; this task never dies.

use std::{sync::Arc, time::Duration};

use super::SyncDb;
use crate::{
    config::Config,
    state::{AppState, DbState},
};
use axum::extract::FromRef;

async fn build(cfg: &Config) -> Option<SyncDb> {
    turso::sync::Builder::new_remote(&cfg.replica_path)
        .with_remote_url(cfg.normalized_url())
        .with_auth_token(cfg.turso_token.clone())
        .bootstrap_if_empty(true)
        .build()
        .await
        .map(std::sync::Arc::new)
        .map_err(|e| tracing::warn!("sync build failed: {e}"))
        .ok()
}

/// One-shot connect for commands: build, converge once, hand over.
pub async fn ready_db(cfg: &Config) -> Option<SyncDb> {
    let db = build(cfg).await?;
    if let Err(e) = db.pull().await {
        tracing::warn!("seed pull failed: {e}");
        return None;
    }
    Some(db)
}

fn record_pull(metrics: &crate::state::SharedMetrics, had: bool) {
    use std::sync::atomic::Ordering::Relaxed;
    if had {
        metrics.pulls_applied.fetch_add(1, Relaxed);
        tracing::debug!("pull: changes applied");
    } else {
        metrics.pulls_empty.fetch_add(1, Relaxed);
        tracing::debug!("pull: no changes");
    }
}

/// Owns the replica for the process lifetime. Builds in the background so
/// serve never blocks on it, fills the connection pool while the IO worker is
/// still free, then re-pulls every `SYNC_SECS`.
pub fn spawn_sync_task(state: &AppState, cfg: Config) {
    if !cfg.has_db() {
        tracing::warn!("no TURSO_DB_URL/TOKEN, db routes will return 503");
        return;
    }
    let cell = Arc::clone(&state.db);
    let metrics = Arc::clone(&state.metrics);
    let write_mutex = Arc::clone(&state.write_mutex);
    let contract_ok = Arc::clone(&state.contract_ok);
    let probe = DbState::from_ref(state);
    tokio::spawn(async move {
        let mut ensured = false;
        let mut last_purge = tokio::time::Instant::now();
        loop {
            if cell.read().await.is_none() {
                match build(&cfg).await {
                    Some(db) => {
                        // Fill the pool before any pull runs: while the worker
                        // is free, connect() is millis, not a queued op.
                        probe.conns.fill(&db).await;
                        *cell.write().await = Some(db);
                        tracing::info!("replica ready");
                    }
                    None => tokio::time::sleep(Duration::from_secs(5)).await,
                }
                continue;
            }
            if !ensured {
                ensured = true;
                let Some(db) = cell.read().await.clone() else {
                    continue;
                };
                // Converge first: the file may predate cloud changes, and the
                // seed decision below must read the truth, not a stale copy.
                match db.pull().await {
                    Ok(had) => record_pull(&metrics, had),
                    Err(e) => {
                        tracing::warn!("first pull failed, will retry: {e}");
                        ensured = false;
                        tokio::time::sleep(Duration::from_secs(10)).await;
                        continue;
                    }
                }
                if let Err(e) = super::accounts::ensure_auth_tables(&probe).await {
                    tracing::warn!("auth tables not ready, will retry: {e}");
                    ensured = false;
                    tokio::time::sleep(Duration::from_secs(10)).await;
                    continue;
                }
                match super::schema::check_version(&probe).await {
                    Ok(true) => {
                        contract_ok.store(true, std::sync::atomic::Ordering::Relaxed);
                    }
                    Ok(false) => {
                        contract_ok.store(false, std::sync::atomic::Ordering::Relaxed);
                        tracing::error!("contract version mismatch: refusing to trust replica");
                    }
                    Err(e) => {
                        tracing::warn!("contract check failed, will retry: {e}");
                        ensured = false;
                        tokio::time::sleep(Duration::from_secs(10)).await;
                    }
                }
                continue;
            }
            // Interval between pulls, not a long-poll window: we wake, pull
            // once, and leave the IO worker free until the next tick.
            tokio::time::sleep(Duration::from_secs(cfg.sync_secs)).await;
            let Some(db) = cell.read().await.clone() else {
                continue;
            };
            let pulled = {
                // Serialized with writes: a pull must never interleave an
                // unpushed local write, or the engine can discard it.
                // The lock drops before the re-check below, which may write.
                let _w = write_mutex.lock().await;
                db.pull().await
            };
            if last_purge.elapsed() >= Duration::from_secs(3600) {
                last_purge = tokio::time::Instant::now();
                match super::accounts::purge_expired(&probe).await {
                    Ok(0) => {}
                    Ok(n) => tracing::info!("purged {n} expired sessions"),
                    Err(e) => tracing::warn!("session purge failed: {e}"),
                }
            }
            match pulled {
                Ok(true) => {
                    record_pull(&metrics, true);
                    match super::schema::check_version(&probe).await {
                        Ok(ok) => {
                            let was = contract_ok.swap(ok, std::sync::atomic::Ordering::Relaxed);
                            if !ok && was {
                                tracing::error!(
                                    "contract version mismatch: refusing to trust replica"
                                );
                            }
                        }
                        Err(e) => tracing::warn!("contract re-check failed: {e}"),
                    }
                }
                Ok(false) => record_pull(&metrics, false),
                Err(e) => {
                    tracing::warn!("pull failed: {e}");
                    tokio::time::sleep(Duration::from_secs(5)).await;
                }
            }
        }
    });
}
