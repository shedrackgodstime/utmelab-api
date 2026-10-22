//! Replica lifecycle. Builds the synced database in the background so
//! serving never blocks on it, fills the connection pool while the engine's IO
//! worker is still free, then re-pulls on its own interval. We deliberately do
//! not long-poll: a pull in flight occupies that worker, and `connect()`/`push()`
//! on the serving path would queue behind it.
//!
//! The interval is the point: the replica is pulled every `SYNC_SECS` whether
//! or not a request arrives, so a change made anywhere (the pipeline promoting
//! content, a key revoked elsewhere) lands on this replica within `SYNC_SECS`.
//! An idle process therefore costs one pull per window and nothing else: no
//! held request, no busy loop, and only the pull's own ~2.3KB of local log
//! writes. `SYNC_SECS` is both the bound on propagation delay and the single
//! knob for freshness against chatter (see its doc in `config`).
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

/// Count a completed pull by whether it carried changes. The attempt time is
/// stamped by the caller, before the pull, so a failed pull still leaves a
/// freshness trace for the ops view.
fn record_pull(metrics: &SharedMetrics, had: bool) {
    use std::sync::atomic::Ordering::Relaxed;
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
    let window = Duration::from_secs(cfg.sync_secs);
    tokio::spawn(async move {
        let db = open(&probe, &cfg).await;
        converge(&probe, &db).await;
        supervise(&probe, window, &db).await;
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
        match super::schema::check_contract(probe).await {
            Ok(None) => {
                probe
                    .contract_ok
                    .store(true, std::sync::atomic::Ordering::Relaxed);
                update_bank_version(probe).await;
                return;
            }
            Ok(Some(why)) => {
                probe
                    .contract_ok
                    .store(false, std::sync::atomic::Ordering::Relaxed);
                tracing::error!("schema contract broken ({why}): data surfaces now fail closed");
                return;
            }
            Err(e) => {
                tracing::warn!("contract check failed, will retry: {e}");
                tokio::time::sleep(READY_RETRY).await;
            }
        }
    }
}

/// Steady state: one pull per `window`, under the write mutex so a pull can
/// never interleave an unpushed local write. This runs whatever the traffic, and
/// that is what lets an unattended process converge: a change made in the cloud
/// lands within one window instead of waiting for the next request. Re-checks
/// the contract when changes land, and purges expired sessions hourly. A failed
/// pull retries on the short gap rather than waiting out the whole window.
async fn supervise(probe: &DbState, window: Duration, db: &SyncDb) {
    let mut last_purge = tokio::time::Instant::now();
    let mut wait = window;
    loop {
        tokio::time::sleep(wait).await;
        // Stamp the attempt before pulling, so ops still sees the poll running
        // while the remote is unreachable.
        probe
            .metrics
            .last_pull_unix
            .store(now_unix(), std::sync::atomic::Ordering::Relaxed);
        let pulled = {
            let _w = probe.write_mutex.lock().await;
            db.pull().await
        };
        wait = match pulled {
            Ok(true) => {
                record_pull(&probe.metrics, true);
                recheck_contract(probe).await;
                window
            }
            Ok(false) => {
                record_pull(&probe.metrics, false);
                window
            }
            Err(e) => {
                tracing::warn!("pull failed: {e}");
                // Retry on the short gap, not the whole window, so a blip does
                // not cost a full interval of freshness.
                PULL_RETRY
            }
        };
        if last_purge.elapsed() >= PURGE_EVERY {
            last_purge = tokio::time::Instant::now();
            match super::accounts::purge_expired(probe).await {
                Ok(0) => {}
                Ok(n) => tracing::info!("purged {n} expired sessions"),
                Err(e) => tracing::warn!("session purge failed: {e}"),
            }
        }
    }
}

async fn update_bank_version(probe: &DbState) {
    let rev = if let Some(db) = probe.db.read().await.clone() {
        db.stats().await.ok().and_then(|st| st.revision)
    } else {
        None
    };
    let ver = match rev {
        Some(r) if !r.trim().is_empty() => r,
        _ => super::schema::read_bank_version(probe).await,
    };
    if let Ok(mut w) = probe.bank_version.write() {
        *w = ver;
    }
}

async fn recheck_contract(probe: &DbState) {
    match super::schema::check_contract(probe).await {
        Ok(None) => {
            let was = probe
                .contract_ok
                .swap(true, std::sync::atomic::Ordering::Relaxed);
            update_bank_version(probe).await;
            if !was {
                tracing::info!("schema contract restored: data surfaces resume");
            }
        }
        Ok(Some(why)) => {
            let was = probe
                .contract_ok
                .swap(false, std::sync::atomic::Ordering::Relaxed);
            if was {
                tracing::error!("schema contract broken ({why}): data surfaces now fail closed");
            }
        }
        Err(e) => tracing::warn!("contract re-check failed: {e}"),
    }
}

/// Engine-side sync figures for the ops status, read-only. `None` when no
/// replica is attached yet: absence is honest, never zeros. This never
/// checkpoints; checkpointing is the engine's own job.
pub async fn stats(
    s: &DbState,
) -> Result<Option<crate::core::models::SyncStats>, crate::error::AppError> {
    let Some(db) = s.db.read().await.clone() else {
        return Ok(None);
    };
    let st = db.stats().await.map_err(super::upstream)?;
    Ok(Some(crate::core::models::SyncStats {
        cdc_operations: st.cdc_operations,
        main_wal_size: st.main_wal_size,
        revert_wal_size: st.revert_wal_size,
        last_pull_unix: st.last_pull_unix_time,
        last_push_unix: st.last_push_unix_time,
        revision: st.revision,
        network_sent_bytes: st.network_sent_bytes,
        network_received_bytes: st.network_received_bytes,
    }))
}

#[cfg(test)]
mod tests {
    use crate::testing::{db_state, db_state_without_db, replica};

    /// A replica answers engine figures; with none attached the field is
    /// honestly absent, so the ops status never invents zeros.
    #[tokio::test]
    async fn stats_reports_figures_only_with_a_replica() {
        let with = db_state(replica().await);
        let st = super::stats(&with).await.expect("stats").expect("some");
        assert!(
            st.last_push_unix.is_none(),
            "a replica that never pushed states no push time"
        );

        let without = db_state_without_db(true, 1);
        assert!(super::stats(&without).await.expect("stats").is_none());
    }

    /// The property the interval exists for: the replica converges with no
    /// request at all, so a change made anywhere in the cloud lands within the
    /// window even on a server nobody is using. A demand-driven pull fails this.
    #[tokio::test]
    async fn the_replica_is_pulled_with_no_request() {
        let s = db_state(replica().await);
        let db = s.db.read().await.clone().expect("replica");
        let task = tokio::spawn({
            let probe = s.clone();
            async move { super::supervise(&probe, std::time::Duration::from_millis(20), &db).await }
        });
        tokio::time::sleep(std::time::Duration::from_millis(150)).await;
        task.abort();
        assert!(
            s.metrics
                .last_pull_unix
                .load(std::sync::atomic::Ordering::Relaxed)
                > 0,
            "an unattended process must still pull, or it never converges"
        );
    }
}
