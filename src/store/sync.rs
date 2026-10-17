//! Replica lifecycle. Builds the synced database in the background so
//! serving never blocks on it, fills the connection pool while the engine's IO
//! worker is still free, then refreshes on demand. We deliberately do not
//! long-poll: a pull in flight occupies that worker, and `connect()`/`push()`
//! on the serving path would queue behind it.
//!
//! Refresh is demand-driven. The supervisor parks on [`Freshness`] and a pull
//! runs only when a request asks for fresh data, at most once per `SYNC_SECS`.
//! An idle process therefore pulls nothing, purges nothing, and asks nothing of
//! the cloud: it does no work at all until traffic arrives. `SYNC_SECS` is the
//! single knob for freshness against chatter.
//!
//! Nothing here ever returns. Every failure is retried on the next request, so
//! the replica recovers without a process restart.

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

/// Demand-driven refresh gate. The supervisor parks on `notify` and wakes only
/// when a request says it wants fresh data; `due_at_unix` coalesces a burst
/// into one pull per `window_secs`. An idle process never wakes it, so it makes
/// no request and does no work when nobody is asking.
pub struct Freshness {
    notify: tokio::sync::Notify,
    /// Unix second from which the next pull is allowed. 0 = immediately.
    due_at_unix: std::sync::atomic::AtomicU64,
    /// Cadence of a successful pull.
    window_secs: u64,
}

impl Freshness {
    pub fn new(window_secs: u64) -> Self {
        Self {
            notify: tokio::sync::Notify::new(),
            due_at_unix: std::sync::atomic::AtomicU64::new(0),
            window_secs,
        }
    }

    fn due_at(&self, now: u64) -> bool {
        now >= self.due_at_unix.load(std::sync::atomic::Ordering::Relaxed)
    }

    /// A request wants fresh data. Wake the supervisor only when a pull is
    /// allowed, so sustained traffic never wakes it per request and pulls at
    /// most once per window. Returns whether it woke it, for tests.
    pub fn touch(&self) -> bool {
        self.touch_at(now_unix())
    }

    fn touch_at(&self, now: u64) -> bool {
        if !self.due_at(now) {
            return false;
        }
        self.notify.notify_one();
        true
    }

    /// Park until a request asks for fresh data.
    pub async fn wanted(&self) {
        self.notify.notified().await;
    }

    /// A pull succeeded: hold the next one for a full window.
    fn refreshed_at(&self, now: u64) {
        self.due_at_unix
            .store(now + self.window_secs, std::sync::atomic::Ordering::Relaxed);
    }

    /// A pull failed: allow a retry after `gap`, still only on the next request.
    fn retry_at(&self, now: u64, gap: u64) {
        self.due_at_unix
            .store(now + gap, std::sync::atomic::Ordering::Relaxed);
    }
}

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
        // converge pulled once, so hold the next pull for a full window.
        probe.freshness.refreshed_at(now_unix());
        supervise(&probe, &db).await;
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

/// Steady state: pull only when a request asks for fresh data, at most once
/// per `SYNC_SECS`, under the write mutex so a pull can never interleave an
/// unpushed local write. Re-checks the contract when changes land, and purges
/// expired sessions (at most hourly) on the same activity gate. An idle process
/// parks here and pulls nothing.
async fn supervise(probe: &DbState, db: &SyncDb) {
    let mut last_purge = tokio::time::Instant::now();
    loop {
        probe.freshness.wanted().await;
        let now = now_unix();
        if !probe.freshness.due_at(now) {
            // A permit left by a burst another pull already answered.
            continue;
        }
        let pulled = {
            let _w = probe.write_mutex.lock().await;
            db.pull().await
        };
        let now = now_unix();
        match pulled {
            Ok(true) => {
                probe.freshness.refreshed_at(now);
                record_pull(&probe.metrics, true);
                recheck_contract(probe).await;
            }
            Ok(false) => {
                probe.freshness.refreshed_at(now);
                record_pull(&probe.metrics, false);
            }
            Err(e) => {
                // Retry on the next request after the short gap, never on a
                // timer: a dead remote must not spin while nobody is asking.
                tracing::warn!("pull failed: {e}");
                probe.freshness.retry_at(now, PULL_RETRY.as_secs());
            }
        }
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

async fn recheck_contract(probe: &DbState) {
    match super::schema::check_contract(probe).await {
        Ok(None) => {
            let was = probe
                .contract_ok
                .swap(true, std::sync::atomic::Ordering::Relaxed);
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
/// replica is attached yet — absence is honest, never zeros. This never
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

    /// The refresh gate: a burst coalesces into one pull per window, and a
    /// failure retries on the short gap rather than the whole window.
    #[tokio::test]
    async fn a_burst_pulls_at_most_once_per_window() {
        let f = super::Freshness::new(60);
        // Due at construction, so the first arrival wakes it.
        assert!(f.touch_at(1_000), "the first request is due");
        f.refreshed_at(1_000);
        // Inside the window: no wake, so a busy client costs nothing extra.
        assert!(!f.due_at(1_059));
        assert!(!f.touch_at(1_059));
        // The boundary wakes it once.
        assert!(f.due_at(1_060));
        assert!(f.touch_at(1_060));
        // A failure retries on the short gap, not the whole window.
        f.retry_at(1_060, 5);
        assert!(!f.due_at(1_064));
        assert!(f.due_at(1_065));
    }

    #[tokio::test]
    async fn the_supervisor_parks_until_a_request_asks() {
        let f = super::Freshness::new(60);
        // No traffic: the wait never completes.
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(100), f.wanted())
                .await
                .is_err(),
            "an idle process must not wake the supervisor"
        );
        // A due request releases it.
        assert!(f.touch());
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(100), f.wanted())
                .await
                .is_ok()
        );
    }
}
