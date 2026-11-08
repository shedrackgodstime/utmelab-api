//! Replica lifecycle. Builds the synced database in the background, fills the
//! connection pool while the engine's IO worker is free, then uses a long-poll
//! pull loop and a separately signalled push loop.
//!
//! Pulls use Turso long-polling, so the remote request waits for a change or a
//! short server-side timeout instead of generating empty interval requests.
//! After five idle minutes, even that wait sleeps completely. The first
//! database request after sleep performs one locked pull before reading.
//!
//! Every engine call goes through [`Engine`] with an explicit budget. Every
//! retry delay and every readiness answer comes from [`SyncPolicy`] and
//! [`SyncStatus`]. Nothing here invents either.

mod engine;
mod policy;
mod state;

#[cfg(test)]
mod enforcement;

pub(crate) use engine::Engine;
pub use policy::{
    admit_write, Budget, BudgetSet, ErrorClass, FreshnessPolicy, PendingWork, RetryPolicy,
    SyncError, SyncPolicy, Timestamp, WriteAdmissionPolicy, WriteDecision, WriteRejection,
};
pub use state::{
    BlockedReason, DegradedReason, Readiness, SyncEvent, SyncHealth, SyncState, SyncStatus,
    Transition,
};

use std::time::Duration;

use super::SyncDb;
use crate::{
    config::Config,
    state::{AppState, DbState, SharedMetrics},
};
use axum::extract::FromRef;
use policy::{PURGE_EVERY, PUSH_FALLBACK, SLEEP_RECHECK};

async fn build(cfg: &Config, policy: &SyncPolicy) -> Result<SyncDb, SyncError> {
    let future = turso::sync::Builder::new_remote(&cfg.replica_path)
        .with_remote_url(cfg.normalized_url())
        .with_auth_token(cfg.turso_token.clone())
        .with_long_poll_timeout(Duration::from_secs(cfg.sync_long_poll_secs))
        .bootstrap_if_empty(true)
        .build();
    match tokio::time::timeout(policy.budgets.build.duration(), future).await {
        Ok(Ok(db)) => Ok(std::sync::Arc::new(db)),
        Ok(Err(error)) => Err(SyncError::new(
            policy::classify_engine(&error),
            error.to_string(),
        )),
        Err(_) => Err(SyncError::timeout("build", policy.budgets.build)),
    }
}

/// One-shot connect for commands: build, converge once, hand over.
pub async fn ready_db(cfg: &Config) -> Option<SyncDb> {
    let policy = SyncPolicy::from_config(cfg);
    let db = match build(cfg, &policy).await {
        Ok(db) => db,
        Err(error) => {
            tracing::warn!(class = error.class.as_str(), error = %error.message, "sync build failed");
            return None;
        }
    };
    if let Err(error) = Engine::new(db.clone(), policy.budgets).pull().await {
        tracing::warn!(class = error.class.as_str(), error = %error.message, "seed pull failed");
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
/// stamped by the status model, before the pull, so a failed pull still leaves
/// a freshness trace for the ops view.
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

fn record_failure(metrics: &SharedMetrics) {
    metrics
        .sync_failures
        .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
}

/// The sleep after a failed attempt comes from the reducer, never from a
/// literal at the call site. It returns true when shutdown requested the
/// sleep to end early.
async fn sleep_or_stop(sync: &SyncStatus, duration: Duration) -> bool {
    if sync.stop_requested() {
        return true;
    }
    tokio::select! {
        _ = sync.wait_for_stop() => true,
        _ = tokio::time::sleep(duration) => false,
    }
}

async fn retry_after(sync: &SyncStatus, transition: &Transition, policy: &SyncPolicy) -> bool {
    let delay = transition
        .retry
        .map(|retry| retry.delay)
        .unwrap_or(policy.retry.base);
    sleep_or_stop(sync, delay).await
}

/// Retained ownership of the background sync supervisor. Dropping the handle
/// does not stop the task, but the owner is explicit and shutdown joins the
/// tree instead of pretending the runtime will do it silently.
pub struct SyncTaskHandle {
    supervisor: Option<tokio::task::JoinHandle<()>>,
    probe: DbState,
}

/// Owns the replica for the process lifetime. The returned handle owns the
/// supervisor task, and the supervisor owns each sync root attempt.
pub fn spawn_sync_task(state: &AppState, cfg: Config) -> SyncTaskHandle {
    let probe = DbState::from_ref(state);
    if !cfg.has_db() {
        state.sync.mark_blocked(BlockedReason::MissingReplica);
        tracing::warn!("no TURSO_DB_URL/TOKEN, db routes will return 503");
        return SyncTaskHandle {
            supervisor: None,
            probe,
        };
    }
    state
        .metrics
        .last_request_unix
        .store(unix_now(), std::sync::atomic::Ordering::Relaxed);
    let supervisor_probe = probe.clone();
    let policy = state.sync.policy().clone();
    let idle_after = Duration::from_secs(cfg.sync_mode.idle_after_secs());
    let supervisor = tokio::spawn(async move {
        run_sync_supervisor(supervisor_probe, cfg, policy, idle_after).await
    });
    SyncTaskHandle {
        supervisor: Some(supervisor),
        probe,
    }
}

impl SyncTaskHandle {
    /// Stop new work, let the supervised tree finish, then make one final
    /// bounded push if local work is still pending. The caller owns the
    /// server lifecycle and should await this after the HTTP service has
    /// drained.
    pub async fn shutdown(mut self) {
        let policy = self.probe.sync.policy().clone();
        self.probe.sync.begin_stop();

        if let Some(supervisor) = self.supervisor.take() {
            match tokio::time::timeout(policy.budgets.shutdown.duration(), supervisor).await {
                Ok(Ok(())) => {}
                Ok(Err(error)) if error.is_cancelled() => {
                    tracing::info!("sync supervisor was cancelled during shutdown");
                }
                Ok(Err(error)) => {
                    tracing::warn!(error = %error, "sync supervisor ended with an error during shutdown");
                }
                Err(_) => {
                    tracing::warn!("sync supervisor exceeded the shutdown budget and was aborted");
                }
            }
        }

        final_push_if_pending(&self.probe, &policy).await;
        self.probe.sync.apply(SyncEvent::Stopped { at: unix_now() });
    }
}

async fn run_sync_root(probe: DbState, cfg: Config, policy: SyncPolicy, idle_after: Duration) {
    let Some(db) = open(&probe, &cfg, &policy).await else {
        return;
    };
    converge(&probe, &db, &policy).await;
    if probe.sync.stop_requested() {
        return;
    }
    let push_probe = probe.clone();
    let push_db = db.clone();
    let push_policy = policy.clone();
    let mut push_handle =
        tokio::spawn(async move { supervise_push(push_probe, push_db, push_policy).await });
    supervise(&probe, &db, idle_after, &policy).await;
    if tokio::time::timeout(policy.budgets.shutdown.duration(), &mut push_handle)
        .await
        .is_err()
    {
        push_handle.abort();
    }
}

fn restart_delay(policy: &SyncPolicy, attempts: u32, state: SyncState) -> Duration {
    if matches!(state, SyncState::Blocked(_)) {
        policy.retry.permanent_probe
    } else {
        policy.retry_delay(attempts.max(1), ErrorClass::Unknown, 0.0)
    }
}

async fn run_sync_supervisor(
    probe: DbState,
    cfg: Config,
    policy: SyncPolicy,
    idle_after: Duration,
) {
    let mut attempts = 0u32;
    loop {
        if probe.sync.stop_requested() {
            return;
        }
        let root_probe = probe.clone();
        let root_cfg = cfg.clone();
        let root_policy = policy.clone();
        let mut root = tokio::spawn(async move {
            run_sync_root(root_probe, root_cfg, root_policy, idle_after).await
        });
        let heartbeat_interval =
            Duration::from_secs(policy.freshness.heartbeat_max_age.as_secs().max(3) / 3);
        let mut heartbeat_tick = tokio::time::interval(heartbeat_interval);
        let outcome = loop {
            tokio::select! {
                result = &mut root => break result,
                _ = probe.sync.wait_for_stop() => {
                    root.abort();
                    break Ok(());
                }
                _ = heartbeat_tick.tick() => {
                    let now = unix_now();
                    let health = probe.sync.health();
                    if health.heartbeat_age_secs(now) > policy.freshness.heartbeat_max_age.as_secs() {
                        tracing::warn!(
                            event = "sync_supervisor_stalled",
                            heartbeat_age_secs = health.heartbeat_age_secs(now),
                            "sync root heartbeat is stale; aborting it for restart"
                        );
                        probe.sync.mark_blocked(BlockedReason::SupervisorStalled);
                        root.abort();
                        break root.await;
                    }
                }
            }
        };
        if probe.sync.stop_requested() {
            return;
        }
        attempts = attempts.saturating_add(1);
        match outcome {
            Ok(()) => {
                if !matches!(probe.sync.state(), SyncState::Blocked(_)) {
                    probe.sync.mark_blocked(BlockedReason::SupervisorStalled);
                }
                tracing::warn!(
                    event = "sync_root_finished",
                    state = probe.sync.state().label(),
                    "sync root finished unexpectedly; it will be restarted"
                );
            }
            Err(error) if error.is_cancelled() => {
                if !matches!(probe.sync.state(), SyncState::Blocked(_)) {
                    probe.sync.mark_blocked(BlockedReason::SupervisorStalled);
                }
                tracing::warn!(
                    event = "sync_root_cancelled",
                    state = probe.sync.state().label(),
                    "sync root was cancelled unexpectedly; it will be restarted"
                );
            }
            Err(error) => {
                if !matches!(probe.sync.state(), SyncState::Blocked(_)) {
                    probe.sync.mark_blocked(BlockedReason::SupervisorStalled);
                }
                record_failure(&probe.metrics);
                tracing::error!(
                    event = "sync_root_panicked",
                    error = %error,
                    state = probe.sync.state().label(),
                    "sync root panicked; it will be restarted"
                );
            }
        }
        let delay = restart_delay(&policy, attempts, probe.sync.state());
        if sleep_or_stop(&probe.sync, delay).await {
            return;
        }
    }
}

async fn final_push_if_pending(probe: &DbState, policy: &SyncPolicy) {
    if !probe.sync.push_pending() {
        return;
    }
    let Some(db) = probe.db.read().await.clone() else {
        return;
    };
    let mut budgets = policy.budgets;
    budgets.push = policy.budgets.shutdown;
    probe.sync.apply(SyncEvent::PushStarted { at: unix_now() });
    let result = tokio::time::timeout(policy.budgets.shutdown.duration(), async {
        let _w = probe.write_mutex.lock().await;
        Engine::new(db, budgets).push().await
    })
    .await;
    match result {
        Ok(Ok(())) => {
            probe
                .sync
                .apply(SyncEvent::PushSucceeded { at: unix_now() });
            tracing::info!("final sync push completed during shutdown");
        }
        Ok(Err(error)) => {
            record_failure(&probe.metrics);
            probe.sync.apply(SyncEvent::PushFailed {
                error,
                at: unix_now(),
            });
            tracing::warn!("final sync push failed during shutdown");
        }
        Err(_) => {
            record_failure(&probe.metrics);
            probe.sync.apply(SyncEvent::PushFailed {
                error: SyncError::timeout("shutdown push", policy.budgets.shutdown),
                at: unix_now(),
            });
            tracing::warn!("final sync push exceeded the shutdown budget");
        }
    }
}

/// Build the replica and publish it, retrying until it exists. A permanent
/// failure still blocks readiness, but the loop keeps a slow probe so an
/// operator can fix the environment without a restart.
async fn open(probe: &DbState, cfg: &Config, policy: &SyncPolicy) -> Option<SyncDb> {
    loop {
        if probe.sync.stop_requested() {
            return None;
        }
        probe.sync.apply(SyncEvent::Heartbeat { at: unix_now() });
        if let Some(db) = probe.db.read().await.clone() {
            probe
                .sync
                .apply(SyncEvent::BuildSucceeded { at: unix_now() });
            return Some(db);
        }
        probe.sync.apply(SyncEvent::BuildStarted { at: unix_now() });
        match build(cfg, policy).await {
            Ok(db) => {
                // Fill the pool before any pull runs: while the worker is
                // free, connect() is millis, not a queued op.
                probe.conns.fill(&db, policy.budgets).await;
                *probe.db.write().await = Some(db.clone());
                probe
                    .sync
                    .apply(SyncEvent::BuildSucceeded { at: unix_now() });
                tracing::info!("replica ready");
                return Some(db);
            }
            Err(error) => {
                record_failure(&probe.metrics);
                let transition = probe.sync.apply(SyncEvent::BuildFailed {
                    error,
                    at: unix_now(),
                });
                if retry_after(&probe.sync, &transition, policy).await {
                    return None;
                }
            }
        }
    }
}

/// Bring the replica to a known state before serving reads: converge with
/// cloud, ensure our tables, confirm the schema contract. The first pull is
/// serialized with local writes exactly like a steady-state pull.
async fn converge(probe: &DbState, db: &SyncDb, policy: &SyncPolicy) {
    probe
        .sync
        .apply(SyncEvent::VerifyStarted { at: unix_now() });
    loop {
        // Converge first: the file may predate cloud changes, and the check
        // below must read the truth, not a stale copy. The write lock makes
        // this pull indistinguishable from the steady-state one.
        probe.sync.apply(SyncEvent::Heartbeat { at: unix_now() });
        probe.sync.apply(SyncEvent::PullStarted { at: unix_now() });
        let pulled = {
            let _w = probe.write_mutex.lock().await;
            Engine::new(db.clone(), policy.budgets).pull().await
        };
        match pulled {
            Ok(had) => {
                record_pull(&probe.metrics, had);
                probe.sync.apply(SyncEvent::PullSucceeded {
                    changes: had,
                    at: unix_now(),
                });
            }
            Err(error) => {
                record_failure(&probe.metrics);
                let transition = probe.sync.apply(SyncEvent::PullFailed {
                    error,
                    at: unix_now(),
                });
                if retry_after(&probe.sync, &transition, policy).await {
                    return;
                }
                continue;
            }
        }

        match tokio::time::timeout(
            policy.budgets.verify.duration(),
            super::accounts::ensure_auth_tables(probe),
        )
        .await
        {
            Ok(Ok(())) => {}
            Ok(Err(error)) => {
                record_failure(&probe.metrics);
                let error = SyncError::new(state::classify(&error), error.to_string());
                let transition = probe.sync.apply(SyncEvent::VerifyFailed {
                    error,
                    at: unix_now(),
                });
                if retry_after(&probe.sync, &transition, policy).await {
                    return;
                }
                continue;
            }
            Err(_) => {
                record_failure(&probe.metrics);
                let error = SyncError::timeout("verify", policy.budgets.verify);
                let transition = probe.sync.apply(SyncEvent::VerifyFailed {
                    error,
                    at: unix_now(),
                });
                if retry_after(&probe.sync, &transition, policy).await {
                    return;
                }
                continue;
            }
        }

        match tokio::time::timeout(
            policy.budgets.verify.duration(),
            super::schema::check_contract(probe),
        )
        .await
        {
            Ok(Ok(None)) => {
                probe
                    .sync
                    .apply(SyncEvent::ContractVerified { at: unix_now() });
                update_bank_version(probe, policy).await;
                return;
            }
            Ok(Ok(Some(why))) => {
                probe.sync.apply(SyncEvent::ContractMismatch {
                    reason: why.clone(),
                    at: unix_now(),
                });
                tracing::error!("schema contract broken ({why}): data surfaces now fail closed");
                return;
            }
            Ok(Err(error)) => {
                record_failure(&probe.metrics);
                let error = SyncError::new(state::classify(&error), error.to_string());
                let transition = probe.sync.apply(SyncEvent::VerifyFailed {
                    error,
                    at: unix_now(),
                });
                if retry_after(&probe.sync, &transition, policy).await {
                    return;
                }
            }
            Err(_) => {
                record_failure(&probe.metrics);
                let error = SyncError::timeout("verify", policy.budgets.verify);
                let transition = probe.sync.apply(SyncEvent::VerifyFailed {
                    error,
                    at: unix_now(),
                });
                if retry_after(&probe.sync, &transition, policy).await {
                    return;
                }
            }
        }
    }
}

/// Steady state long-poll pull loop. Pulls are serialized with local writes so
/// a remote apply can never interleave an unpushed local write. The long poll
/// itself waits in the sync engine; it does not create timer-driven empty
/// requests. After idle sleep, the first request wakes the replica.
async fn supervise(probe: &DbState, db: &SyncDb, idle_after: Duration, policy: &SyncPolicy) {
    let mut last_purge = tokio::time::Instant::now();
    loop {
        if probe.sync.stop_requested() {
            return;
        }
        probe.sync.apply(SyncEvent::Heartbeat { at: unix_now() });
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
            probe.sync.apply(SyncEvent::Heartbeat { at: unix_now() });
            tokio::select! {
                _ = probe.sync.wait_for_stop() => return,
                _ = tokio::time::sleep(SLEEP_RECHECK) => {}
                _ = probe.pull_notify.notified() => {}
            }
            continue;
        }
        probe
            .metrics
            .last_pull_unix
            .store(unix_now(), std::sync::atomic::Ordering::Relaxed);
        probe.sync.apply(SyncEvent::PullStarted { at: unix_now() });
        let started = tokio::time::Instant::now();
        let pulled = {
            let _w = probe.write_mutex.lock().await;
            Engine::new(db.clone(), policy.budgets).pull().await
        };
        probe.metrics.last_pull_duration_ms.store(
            started.elapsed().as_millis().min(u64::MAX as u128) as u64,
            std::sync::atomic::Ordering::Relaxed,
        );
        match pulled {
            Ok(true) => {
                record_pull(&probe.metrics, true);
                probe.sync.apply(SyncEvent::PullSucceeded {
                    changes: true,
                    at: unix_now(),
                });
                recheck_contract(probe, policy).await;
            }
            Ok(false) => {
                record_pull(&probe.metrics, false);
                probe.sync.apply(SyncEvent::PullSucceeded {
                    changes: false,
                    at: unix_now(),
                });
            }
            Err(error) => {
                record_failure(&probe.metrics);
                let transition = probe.sync.apply(SyncEvent::PullFailed {
                    error,
                    at: unix_now(),
                });
                if retry_after(&probe.sync, &transition, policy).await {
                    return;
                }
            }
        };
        if last_purge.elapsed() >= PURGE_EVERY {
            last_purge = tokio::time::Instant::now();
            match tokio::time::timeout(
                policy.budgets.verify.duration(),
                super::accounts::purge_expired(probe),
            )
            .await
            {
                Ok(Ok(0)) => {}
                Ok(Ok(n)) => tracing::info!("purged {n} expired sessions"),
                Ok(Err(e)) => tracing::warn!("session purge failed: {e}"),
                Err(_) => tracing::warn!("session purge exceeded its budget"),
            }
        }
    }
}

/// Push retries are signalled by a failed request write. A slow or long-poll
/// pull therefore cannot block the write handler forever, and the retry path
/// does not issue an empty push on every pull timeout. The long fallback
/// rechecks pending state so a local commit recoverable after a restart is
/// not forgotten, but it does not push when no work is known to be pending.
async fn supervise_push(probe: DbState, db: SyncDb, policy: SyncPolicy) {
    loop {
        if probe.sync.stop_requested() {
            return;
        }
        if probe.sync.push_pending() {
            loop {
                if probe.sync.stop_requested() {
                    return;
                }
                probe.sync.apply(SyncEvent::PushStarted { at: unix_now() });
                let result = {
                    let _w = probe.write_mutex.lock().await;
                    Engine::new(db.clone(), policy.budgets).push().await
                };
                match result {
                    Ok(()) => {
                        probe
                            .sync
                            .apply(SyncEvent::PushSucceeded { at: unix_now() });
                        break;
                    }
                    Err(error) => {
                        record_failure(&probe.metrics);
                        let transition = probe.sync.apply(SyncEvent::PushFailed {
                            error,
                            at: unix_now(),
                        });
                        if retry_after(&probe.sync, &transition, &policy).await {
                            return;
                        }
                    }
                }
            }
        }
        tokio::select! {
            _ = probe.sync.wait_for_stop() => return,
            _ = probe.push_notify.notified() => {}
            _ = tokio::time::sleep(PUSH_FALLBACK) => {}
        }
    }
}

/// Wake a sleeping replica exactly once. The write mutex makes concurrent
/// first requests share one pull instead of creating a pull storm, and the
/// status throttle stops a failing remote from being retried by every request.
pub(crate) async fn wake_if_sleeping(s: &DbState) -> Result<(), crate::error::AppError> {
    use std::sync::atomic::Ordering::Relaxed;
    if s.sync.stop_requested() {
        return Err(crate::error::AppError::DbUnavailable("sync"));
    }
    if !s.metrics.sync_sleeping.load(Relaxed) {
        return Ok(());
    }
    if !s.sync.wake_allowed() {
        return Err(crate::error::AppError::DbUnavailable("sync"));
    }
    let guard = s.write_mutex.lock().await;
    if !s.metrics.sync_sleeping.load(Relaxed) {
        return Ok(());
    }
    let Some(db) = s.db.read().await.clone() else {
        return Err(crate::error::AppError::DbUnavailable("sync"));
    };
    let started = tokio::time::Instant::now();
    let pulled = Engine::new(db.clone(), s.sync.policy().budgets)
        .pull()
        .await;
    match pulled {
        Ok(had) => {
            s.metrics.last_pull_duration_ms.store(
                started.elapsed().as_millis().min(u64::MAX as u128) as u64,
                Relaxed,
            );
            s.metrics.last_pull_unix.store(unix_now(), Relaxed);
            record_pull(&s.metrics, had);
            s.sync.record_wake_success(had, unix_now());
            s.metrics.sync_sleeping.store(false, Relaxed);
            drop(guard);
            // The supervisor slept through the idle window. Tell it the
            // replica is awake so it resumes long-polling now instead of
            // waiting out the full recheck interval.
            s.pull_notify.notify_one();
            if had {
                // A wake pull can be the first observation of a remote
                // revision after the replica slept. Refresh the version now
                // so version-keyed caches cannot serve the pre-sleep tree.
                refresh_bank_version(s, &db).await;
            }
            Ok(())
        }
        Err(error) => {
            record_failure(&s.metrics);
            s.sync.record_wake_failure(&error, unix_now());
            Err(crate::error::AppError::DbUnavailable("sync"))
        }
    }
}

async fn refresh_bank_version(s: &DbState, db: &SyncDb) {
    if let Ok(stats) = Engine::new(db.clone(), s.sync.policy().budgets)
        .stats()
        .await
    {
        if let Some(revision) = stats.revision.filter(|value| !value.trim().is_empty()) {
            if let Ok(mut version) = s.bank_version.write() {
                *version = revision;
            }
        }
    }
}

async fn update_bank_version(probe: &DbState, policy: &SyncPolicy) {
    let rev = if let Some(db) = probe.db.read().await.clone() {
        Engine::new(db, policy.budgets)
            .stats()
            .await
            .ok()
            .and_then(|st| st.revision)
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

async fn recheck_contract(probe: &DbState, policy: &SyncPolicy) {
    match tokio::time::timeout(
        policy.budgets.verify.duration(),
        super::schema::check_contract(probe),
    )
    .await
    {
        Ok(Ok(None)) => {
            let was = probe.sync.state();
            probe
                .sync
                .apply(SyncEvent::ContractVerified { at: unix_now() });
            update_bank_version(probe, policy).await;
            if !matches!(was, SyncState::Ready) {
                tracing::info!("schema contract restored: data surfaces resume");
            }
        }
        Ok(Ok(Some(why))) => {
            let was = probe.sync.state();
            probe.sync.apply(SyncEvent::ContractMismatch {
                reason: why.clone(),
                at: unix_now(),
            });
            if !matches!(was, SyncState::Blocked(BlockedReason::SchemaMismatch)) {
                tracing::error!("schema contract broken ({why}): data surfaces now fail closed");
            }
        }
        Ok(Err(e)) => tracing::warn!("contract re-check failed: {e}"),
        Err(_) => tracing::warn!("contract re-check exceeded its budget"),
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
    let st = Engine::new(db, s.sync.policy().budgets)
        .stats()
        .await
        .map_err(|error| match error.class {
            ErrorClass::Contention => crate::error::AppError::DbContended,
            _ => crate::error::AppError::Upstream(error.message),
        })?;
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
        let policy = s.sync.policy().clone();
        let task = tokio::spawn({
            let probe = s.clone();
            async move {
                super::supervise(&probe, &db, std::time::Duration::from_secs(300), &policy).await
            }
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

    #[test]
    fn restart_delay_uses_the_slow_probe_when_blocked_and_backoff_otherwise() {
        let policy = super::SyncPolicy::default();
        assert_eq!(
            super::restart_delay(
                &policy,
                1,
                super::SyncState::Blocked(super::BlockedReason::SupervisorStalled)
            ),
            policy.retry.permanent_probe
        );
        assert_eq!(
            super::restart_delay(&policy, 1, super::SyncState::Ready),
            policy.retry.base
        );
        assert!(super::restart_delay(&policy, 100, super::SyncState::Ready) <= policy.retry.max);
    }
}
