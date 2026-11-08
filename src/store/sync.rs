//! Replica lifecycle. Builds the synced database in the background, fills the
//! connection pool while the engine's IO worker is free, then uses a long-poll
//! pull loop and a separately signalled push loop.
//!
//! Pulls use Turso long-polling, so the remote request waits for a change or a
//! short server-side timeout instead of generating empty interval requests.
//! After five idle minutes, even that wait sleeps completely. The first
//! database request after sleep performs one locked pull before reading.
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
const SLEEP_RECHECK: Duration = Duration::from_secs(60);

async fn build(cfg: &Config) -> Option<SyncDb> {
    turso::sync::Builder::new_remote(&cfg.replica_path)
        .with_remote_url(cfg.normalized_url())
        .with_auth_token(cfg.turso_token.clone())
        .with_long_poll_timeout(Duration::from_secs(cfg.sync_long_poll_secs))
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

pub(crate) fn unix_now() -> u64 {
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
    state
        .metrics
        .last_request_unix
        .store(unix_now(), std::sync::atomic::Ordering::Relaxed);
    let probe = DbState::from_ref(state);
    let idle_after = Duration::from_secs(cfg.sync_mode.idle_after_secs());
    tokio::spawn(async move {
        let db = open(&probe, &cfg).await;
        converge(&probe, &db).await;
        let push_probe = probe.clone();
        let push_db = db.clone();
        tokio::spawn(async move { supervise_push(push_probe, push_db).await });
        supervise(&probe, &db, idle_after).await;
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
                probe
                    .metrics
                    .sync_failures
                    .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
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

/// Steady state long-poll pull loop. Pulls are serialized with local writes so
/// a remote apply can never interleave an unpushed local write. The long poll
/// itself waits in the sync engine; it does not create timer-driven empty
/// requests. After idle sleep, the first request wakes the replica.
async fn supervise(probe: &DbState, db: &SyncDb, idle_after: Duration) {
    let mut last_purge = tokio::time::Instant::now();
    loop {
        let last_request = probe
            .metrics
            .last_request_unix
            .load(std::sync::atomic::Ordering::Relaxed);
        if last_request != 0 && unix_now().saturating_sub(last_request) >= idle_after.as_secs() {
            probe
                .metrics
                .sync_sleeping
                .store(true, std::sync::atomic::Ordering::Relaxed);
            tracing::info!("replica sync sleeping after idle traffic window");
            tokio::select! {
                _ = tokio::time::sleep(SLEEP_RECHECK) => {}
                _ = probe.pull_notify.notified() => {}
            }
            continue;
        }
        // Stamp the attempt before pulling, so ops still sees the poll running
        // while the remote is unreachable.
        probe
            .metrics
            .last_pull_unix
            .store(unix_now(), std::sync::atomic::Ordering::Relaxed);
        let started = tokio::time::Instant::now();
        let pulled = {
            let _w = probe.write_mutex.lock().await;
            db.pull().await
        };
        probe.metrics.last_pull_duration_ms.store(
            started.elapsed().as_millis().min(u64::MAX as u128) as u64,
            std::sync::atomic::Ordering::Relaxed,
        );
        match pulled {
            Ok(true) => {
                record_pull(&probe.metrics, true);
                recheck_contract(probe).await;
            }
            Ok(false) => {
                record_pull(&probe.metrics, false);
            }
            Err(e) => {
                probe
                    .metrics
                    .sync_failures
                    .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                tracing::warn!("sync push or pull failed: {e}");
                tokio::time::sleep(PULL_RETRY).await;
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

/// Push retries are signalled by a failed request write. A slow or long-poll
/// pull therefore cannot block the write handler forever, and the retry path
/// does not issue an empty push on every pull timeout. The long fallback keeps
/// a pending local commit recoverable after a process restart.
async fn supervise_push(probe: DbState, db: SyncDb) {
    loop {
        loop {
            let result = {
                let _w = probe.write_mutex.lock().await;
                db.push().await
            };
            match result {
                Ok(()) => break,
                Err(e) => {
                    probe
                        .metrics
                        .sync_failures
                        .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    tracing::warn!("push retry failed: {e}");
                    tokio::time::sleep(PULL_RETRY).await;
                }
            }
        }
        tokio::select! {
            _ = probe.push_notify.notified() => {}
            _ = tokio::time::sleep(Duration::from_secs(300)) => {}
        }
    }
}

/// Wake a sleeping replica exactly once. The write mutex makes concurrent
/// first requests share one pull instead of creating a pull storm.
pub(crate) async fn wake_if_sleeping(s: &DbState) -> Result<(), crate::error::AppError> {
    use std::sync::atomic::Ordering::Relaxed;
    if !s.metrics.sync_sleeping.load(Relaxed) {
        return Ok(());
    }
    let _w = s.write_mutex.lock().await;
    if !s.metrics.sync_sleeping.load(Relaxed) {
        return Ok(());
    }
    let Some(db) = s.db.read().await.clone() else {
        return Err(crate::error::AppError::DbUnavailable("sync"));
    };
    let started = tokio::time::Instant::now();
    let had = match db.pull().await.map_err(super::upstream) {
        Ok(had) => had,
        Err(e) => {
            s.metrics
                .sync_failures
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            return Err(e);
        }
    };
    s.metrics.last_pull_duration_ms.store(
        started.elapsed().as_millis().min(u64::MAX as u128) as u64,
        Relaxed,
    );
    s.metrics.last_pull_unix.store(unix_now(), Relaxed);
    record_pull(&s.metrics, had);
    s.metrics.sync_sleeping.store(false, Relaxed);
    if had {
        // A wake pull can be the first observation of a remote revision after
        // the replica slept. Refresh the version now so version-keyed caches
        // cannot serve the pre-sleep discovery tree.
        if let Ok(stats) = db.stats().await {
            if let Some(revision) = stats.revision.filter(|value| !value.trim().is_empty()) {
                if let Ok(mut version) = s.bank_version.write() {
                    *version = revision;
                }
            }
        }
    }
    s.pull_notify.notify_one();
    drop(_w);
    Ok(())
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

    /// The property the pull loop exists for: the replica converges with no
    /// request at all, so a change made anywhere in the cloud lands without
    /// timer-driven empty requests.
    #[tokio::test]
    async fn the_replica_is_pulled_with_no_request() {
        let s = db_state(replica().await);
        let db = s.db.read().await.clone().expect("replica");
        let task = tokio::spawn({
            let probe = s.clone();
            async move { super::supervise(&probe, &db, std::time::Duration::from_secs(300)).await }
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
