//! Replica lifecycle. Builds the synced database in the background so
//! serving never blocks on it, fills the connection pool while the engine's IO
//! worker is still free, then re-pulls on an interval. We deliberately do not
//! long-poll: a pull in flight occupies that worker, and `connect()`/`push()`
//! on the serving path would queue behind it.
//!
//! Idle cost is one small request per `SYNC_SECS` and nothing else: no busy
//! loop, no disk churn, no held connection. `SYNC_SECS` is the single knob
//! for freshness against chatter.
//!
//! Nothing here ever returns. Every failure is retried in place, so the
//! replica recovers without a process restart.

use std::time::Duration;

use super::SyncDb;
use crate::{
    config::Config,
    state::{AppState, DbState, SharedMetrics},
};
use axum::extract::FromRef;

/// Retry delays, kept together so the "never dies" policy reads in one place.
const BUILD_RETRY: Duration = Duration::from_secs(5);
const READY_RETRY: Duration = Duration::from_secs(10);
const PULL_RETRY: Duration = Duration::from_secs(5);
const PURGE_EVERY: Duration = Duration::from_secs(3600);

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

fn now_unix() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn record_pull(metrics: &SharedMetrics, had: bool) {
    use std::sync::atomic::Ordering::Relaxed;
    metrics.last_pull_unix.store(now_unix(), Relaxed);
    if had {
        metrics.pulls_applied.fetch_add(1, Relaxed);
        tracing::debug!("pull: changes applied");
    } else {
        metrics.pulls_empty.fetch_add(1, Relaxed);
        tracing::debug!("pull: no changes");
    }
}

/// Owns the replica for the process lifetime.
pub fn spawn_sync_task(state: &AppState, cfg: Config) {
    if !cfg.has_db() {
        tracing::warn!("no TURSO_DB_URL/TOKEN, db routes will return 503");
        return;
    }
    let probe = DbState::from_ref(state);
    tokio::spawn(async move {
        let db = open(&probe, &cfg).await;
        converge(&probe, &db).await;
        supervise(&probe, &cfg, &db).await;
    });
}

/// Build the replica and publish it, retrying until it exists.
async fn open(probe: &DbState, cfg: &Config) -> SyncDb {
    loop {
        if let Some(db) = probe.db.read().await.clone() {
            return db;
        }
        match build(cfg).await {
            Some(db) => {
                // Fill the pool before any pull runs: while the worker is
                // free, connect() is millis, not a queued op.
                probe.conns.fill(&db).await;
                *probe.db.write().await = Some(db.clone());
                tracing::info!("replica ready");
                return db;
            }
            None => tokio::time::sleep(BUILD_RETRY).await,
        }
    }
}

/// Bring the replica to a known state before serving reads: converge with
/// cloud, ensure our tables, confirm the schema contract. Transient failure
/// retries in place; a version mismatch is recorded, not retried.
async fn converge(probe: &DbState, db: &SyncDb) {
    loop {
        // Converge first: the file may predate cloud changes, and the check
        // below must read the truth, not a stale copy.
        match db.pull().await {
            Ok(had) => record_pull(&probe.metrics, had),
            Err(e) => {
                tracing::warn!("first pull failed, will retry: {e}");
                tokio::time::sleep(READY_RETRY).await;
                continue;
            }
        }
        if let Err(e) = super::accounts::ensure_auth_tables(probe).await {
            tracing::warn!("auth tables not ready, will retry: {e}");
            tokio::time::sleep(READY_RETRY).await;
            continue;
        }
        match super::schema::check_version(probe).await {
            Ok(ok) => {
                probe
                    .contract_ok
                    .store(ok, std::sync::atomic::Ordering::Relaxed);
                if !ok {
                    tracing::error!("contract version mismatch: data surfaces now fail closed");
                }
                return;
            }
            Err(e) => {
                tracing::warn!("contract check failed, will retry: {e}");
                tokio::time::sleep(READY_RETRY).await;
            }
        }
    }
}

/// Steady state: one pull per `SYNC_SECS`, under the write mutex so a pull
/// can never interleave an unpushed local write. Re-checks the contract
/// when changes land, and purges expired sessions hourly.
async fn supervise(probe: &DbState, cfg: &Config, db: &SyncDb) {
    let mut last_purge = tokio::time::Instant::now();
    loop {
        tokio::time::sleep(Duration::from_secs(cfg.sync_secs)).await;
        let pulled = {
            let _w = probe.write_mutex.lock().await;
            db.pull().await
        };
        if last_purge.elapsed() >= PURGE_EVERY {
            last_purge = tokio::time::Instant::now();
            match super::accounts::purge_expired(probe).await {
                Ok(0) => {}
                Ok(n) => tracing::info!("purged {n} expired sessions"),
                Err(e) => tracing::warn!("session purge failed: {e}"),
            }
        }
        match pulled {
            Ok(true) => {
                record_pull(&probe.metrics, true);
                recheck_contract(probe).await;
            }
            Ok(false) => record_pull(&probe.metrics, false),
            Err(e) => {
                tracing::warn!("pull failed: {e}");
                tokio::time::sleep(PULL_RETRY).await;
            }
        }
    }
}

async fn recheck_contract(probe: &DbState) {
    match super::schema::check_version(probe).await {
        Ok(ok) => {
            let was = probe
                .contract_ok
                .swap(ok, std::sync::atomic::Ordering::Relaxed);
            if !ok && was {
                tracing::error!("contract version mismatch: data surfaces now fail closed");
            }
        }
        Err(e) => tracing::warn!("contract re-check failed: {e}"),
    }
}
