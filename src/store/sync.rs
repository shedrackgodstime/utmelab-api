//! Replica lifecycle. Builds the synced database in the background, fills the
//! connection pool while the engine's IO worker is free, then uses a long-poll
//! pull loop and a separately signalled push loop.
//!
//! Pulls use Turso long-polling, so the remote request waits for a change or a
//! short server-side timeout instead of generating empty interval requests.
//! After five idle minutes, even that wait sleeps completely. The first
//! database request after sleep performs one locked pull before reading.
//!
//! Every engine call goes through `Engine` with an explicit budget. Every
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
use policy::{PURGE_EVERY, PUSH_COALESCE, PUSH_FALLBACK};

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

fn should_quarantine_replica(error: &SyncError) -> bool {
    if error.class != ErrorClass::LocalStorage {
        return false;
    }
    let message = error.message.to_ascii_lowercase();
    [
        "corrupt",
        "not a database",
        "notadb",
        "malformed",
        "invalid database",
    ]
    .iter()
    .any(|needle| message.contains(needle))
}

fn replica_header_is_invalid(path: &str) -> Result<bool, String> {
    let file = match std::fs::File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(format!("open {path}: {error}")),
    };
    let mut header = [0_u8; 16];
    let mut reader = std::io::BufReader::new(file);
    use std::io::Read;
    let read = reader
        .read(&mut header)
        .map_err(|error| format!("read {path}: {error}"))?;
    if read == 0 {
        return Ok(false);
    }
    Ok(read >= 16 && header != *b"SQLite format 3\0")
}

fn replica_files(path: &str) -> Vec<String> {
    let mut files = vec![path.to_string()];
    for suffix in ["-wal", "-shm", "-log", "-changes", "-info", "-wal-revert"] {
        files.push(format!("{path}{suffix}"));
    }
    files
}

/// Rename every replica artifact aside and return the move pairs so a failed
/// staged swap can restore the exact files it displaced. Nothing is deleted.
fn quarantine_replica_files(path: &str, label: &str) -> Result<Vec<(String, String)>, String> {
    let candidates = replica_files(path);
    if !candidates
        .iter()
        .any(|candidate| std::path::Path::new(candidate).exists())
    {
        return Ok(Vec::new());
    }
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .subsec_nanos();
    let suffix = format!(".{label}-{}-{nanos}-{}", unix_now(), std::process::id());
    let mut moved = Vec::new();
    for candidate in candidates {
        let candidate_path = std::path::Path::new(&candidate);
        if !candidate_path.exists() {
            continue;
        }
        let target = format!("{candidate}{suffix}");
        if let Err(error) = std::fs::rename(candidate_path, &target) {
            restore_quarantined(&moved);
            return Err(format!("rename {candidate} to {target}: {error}"));
        }
        moved.push((candidate, target));
    }
    Ok(moved)
}

fn quarantine_replica(path: &str) -> Result<bool, String> {
    Ok(!quarantine_replica_files(path, "corrupt")?.is_empty())
}

fn staging_replica_path(path: &str, epoch: u64) -> String {
    format!("{path}.resync-{epoch}-{}", std::process::id())
}

/// Move a verified candidate into the serving path. Refuses to overwrite a
/// replica artifact: the caller must quarantine the serving set first.
fn promote_staged_replica(staging: &str, serving: &str) -> Result<Vec<(String, String)>, String> {
    let occupied = replica_files(serving)
        .into_iter()
        .find(|candidate| std::path::Path::new(candidate).exists());
    if let Some(candidate) = occupied {
        return Err(format!(
            "serving replica artifact still exists: {candidate}"
        ));
    }
    let mut moved = Vec::new();
    for source in replica_files(staging) {
        if !std::path::Path::new(&source).exists() {
            continue;
        }
        let target = source.replacen(staging, serving, 1);
        if let Err(error) = std::fs::rename(&source, &target) {
            for (restored_source, restored_target) in moved.drain(..).rev() {
                if let Err(restore_error) = std::fs::rename(&restored_target, &restored_source) {
                    tracing::error!(
                        event = "sync_resync_promote_rollback_failed",
                        from = %restored_target,
                        to = %restored_source,
                        error = %restore_error,
                        "could not return a staged artifact after a failed promotion"
                    );
                }
            }
            return Err(format!("rename {source} to {target}: {error}"));
        }
        moved.push((source, target));
    }
    if moved.is_empty() {
        return Err(format!("staged replica has no files at {staging}"));
    }
    Ok(moved)
}

fn restore_quarantined(files: &[(String, String)]) {
    for (original, quarantined) in files {
        if let Err(error) = std::fs::rename(quarantined, original) {
            tracing::error!(
                event = "sync_resync_restore_failed",
                from = %quarantined,
                to = %original,
                error = %error,
                "could not restore the displaced replica during rollback"
            );
        }
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

/// Push local committed changes up to the remote database for one-shot commands.
pub async fn push_db(db: &SyncDb, cfg: &Config) -> Result<(), SyncError> {
    let policy = SyncPolicy::from_config(cfg);
    Engine::new(db.clone(), policy.budgets).push().await
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

fn record_push_duration(metrics: &SharedMetrics, started: tokio::time::Instant) {
    use std::sync::atomic::Ordering::Relaxed;
    let ms = started.elapsed().as_millis().min(u64::MAX as u128) as u64;
    metrics.push_count.fetch_add(1, Relaxed);
    metrics.push_ms_total.fetch_add(ms, Relaxed);
    metrics.last_push_duration_ms.store(ms, Relaxed);
    let max = &metrics.push_ms_max;
    let mut current = max.load(Relaxed);
    while ms > current {
        match max.compare_exchange_weak(current, ms, Relaxed, Relaxed) {
            Ok(_) => break,
            Err(actual) => current = actual,
        }
    }
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

async fn run_sync_root(
    probe: DbState,
    cfg: Config,
    policy: SyncPolicy,
    idle_after: Duration,
    already_verified: bool,
) {
    let epoch = probe.sync.resync_epoch();
    let Some(db) = open(&probe, &cfg, &policy).await else {
        return;
    };
    if probe.sync.resync_epoch() != epoch {
        return;
    }
    if !converge(&probe, &probe.sync, &db, &policy, epoch, already_verified).await {
        return;
    }
    if probe.sync.stop_requested() || probe.sync.resync_epoch() != epoch {
        return;
    }
    recover_pending_from_change_log(&probe, &db, &policy).await;
    let push_probe = probe.clone();
    let push_db = db.clone();
    let push_policy = policy.clone();
    let mut push_handle =
        tokio::spawn(async move { supervise_push(push_probe, push_db, push_policy, epoch).await });
    supervise(&probe, &db, idle_after, &policy).await;
    if tokio::time::timeout(policy.budgets.shutdown.duration(), &mut push_handle)
        .await
        .is_err()
    {
        push_handle.abort();
    }
}

async fn recover_pending_from_change_log(probe: &DbState, db: &SyncDb, policy: &SyncPolicy) {
    match Engine::new(db.clone(), policy.budgets).stats().await {
        Ok(stats) if stats.cdc_operations > 0 => {
            probe
                .sync
                .mark_pending_from_change_log(stats.cdc_operations as u64);
            tracing::warn!(
                event = "sync_pending_recovered",
                cdc_operations = stats.cdc_operations,
                "local change-log work recovered after startup"
            );
        }
        Ok(_) => {}
        Err(error) => tracing::warn!(
            class = error.class.as_str(),
            error = %error.message,
            "could not inspect local change log during startup"
        ),
    }
}

fn restart_delay(policy: &SyncPolicy, attempts: u32, state: SyncState) -> Duration {
    if matches!(state, SyncState::Blocked(_)) {
        policy.retry.permanent_probe
    } else {
        policy.retry_delay(attempts.max(1), ErrorClass::Unknown, 0.0)
    }
}

enum SupervisorExit {
    RootFinished(Result<(), tokio::task::JoinError>),
    ResyncDrained,
    Stopping,
    Stalled,
}

/// Wait for committed local work to reach Turso. Writes are already paused by
/// `request_resync`, so this budget closes instead of growing. A timeout aborts
/// the rebuild and keeps the serving replica; it never clears the counters.
async fn drain_before_resync(probe: &DbState, policy: &SyncPolicy) -> bool {
    let started = tokio::time::Instant::now();
    let budget = policy.resync_drain;
    let initial = probe.sync.health();
    tracing::warn!(
        event = "sync_resync_drain_started",
        pending_operations = initial.pending_operations,
        pending_bytes = initial.pending_bytes,
        budget_secs = budget.as_secs(),
        "writes paused while pending local work drains to Turso"
    );
    loop {
        if probe.sync.stop_requested() {
            tracing::warn!(
                event = "sync_resync_drain_aborted",
                reason = "stopping",
                "rebuild aborted during shutdown; serving replica was kept"
            );
            return false;
        }
        let health = probe.sync.health();
        if !health.push_pending {
            tracing::warn!(
                event = "sync_resync_drain_complete",
                waited_ms = started.elapsed().as_millis(),
                "all committed local work reached Turso; staging can begin"
            );
            return true;
        }
        if started.elapsed() >= budget {
            tracing::error!(
                event = "sync_resync_drain_timeout",
                budget_secs = budget.as_secs(),
                pending_operations = health.pending_operations,
                pending_bytes = health.pending_bytes,
                "rebuild aborted; serving replica was kept and writes resumed"
            );
            return false;
        }
        probe.push_notify.notify_waiters();
        let remaining = budget.saturating_sub(started.elapsed()).min(PUSH_COALESCE);
        if sleep_or_stop(&probe.sync, remaining).await {
            tracing::warn!(
                event = "sync_resync_drain_aborted",
                reason = "stopping",
                "rebuild aborted during shutdown; serving replica was kept"
            );
            return false;
        }
    }
}

/// Retirement happens only after the drain succeeds. Advancing the epoch here
/// is what retires the push task; doing it earlier would drop pending work.
async fn prepare_staged_rebuild(
    probe: &DbState,
    root: Option<&mut tokio::task::JoinHandle<()>>,
) -> u64 {
    let epoch = probe.sync.begin_resync_epoch();
    if let Some(handle) = root {
        if !handle.is_finished() {
            handle.abort();
        }
        let _ = handle.await;
    }
    let at = unix_now();
    probe.sync.apply(SyncEvent::Heartbeat { at });
    tracing::warn!(
        event = "sync_resync_started",
        epoch,
        "local work drained; building a staged full replica"
    );
    epoch
}

async fn finish_staged_rebuild(
    probe: &DbState,
    cfg: &Config,
    policy: &SyncPolicy,
    epoch: u64,
) -> bool {
    // The serving replica stays published while the replacement is built off
    // to the side. Only the short swap below can interrupt readers, and a
    // failed swap restores the displaced files. Writes stay paused until then
    // so no committed row is left behind the candidate.
    let swapped = staged_resync(probe, cfg, policy, epoch).await;
    probe.sync.finish_resync();
    if swapped {
        tracing::warn!(
            event = "sync_resync_complete",
            epoch,
            "staged replica is now serving; writes resumed"
        );
    } else {
        tracing::warn!(
            event = "sync_resync_failed",
            epoch,
            "serving replica was kept after a failed staged rebuild; writes resumed"
        );
    }
    swapped
}

async fn run_sync_supervisor(
    probe: DbState,
    cfg: Config,
    policy: SyncPolicy,
    idle_after: Duration,
) {
    let mut attempts = 0u32;
    // A swapped candidate is already verified. Its replacement root must not
    // move the serving replica back through a verifying state, or readers
    // would fail closed again after a successful swap.
    let mut already_verified = false;
    loop {
        if probe.sync.stop_requested() {
            return;
        }
        let root_probe = probe.clone();
        let root_cfg = cfg.clone();
        let root_policy = policy.clone();
        let mut root = tokio::spawn(async move {
            run_sync_root(
                root_probe,
                root_cfg,
                root_policy,
                idle_after,
                already_verified,
            )
            .await
        });
        let heartbeat_interval =
            Duration::from_secs(policy.freshness.heartbeat_max_age.as_secs().max(3) / 3);
        let mut heartbeat_tick = tokio::time::interval(heartbeat_interval);
        let exit = loop {
            tokio::select! {
                result = &mut root => break SupervisorExit::RootFinished(result),
                _ = probe.sync.wait_for_resync() => {
                    if drain_before_resync(&probe, &policy).await {
                        break SupervisorExit::ResyncDrained;
                    }
                    probe.sync.finish_resync();
                    tracing::error!(
                        event = "sync_resync_aborted",
                        "the drain did not finish; serving replica and queued work were kept"
                    );
                    continue;
                }
                _ = probe.sync.wait_for_stop() => break SupervisorExit::Stopping,
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
                        break SupervisorExit::Stalled;
                    }
                }
            }
        };
        if probe.sync.stop_requested() || matches!(exit, SupervisorExit::Stopping) {
            root.abort();
            let _ = root.await;
            return;
        }
        if matches!(exit, SupervisorExit::ResyncDrained) {
            attempts = 0;
            let epoch = prepare_staged_rebuild(&probe, Some(&mut root)).await;
            already_verified = finish_staged_rebuild(&probe, &cfg, &policy, epoch).await;
            continue;
        }
        if matches!(exit, SupervisorExit::Stalled) {
            root.abort();
            let _ = root.await;
        }
        already_verified = false;
        attempts = attempts.saturating_add(1);
        let outcome = match exit {
            SupervisorExit::RootFinished(result) => result,
            SupervisorExit::Stalled => Ok(()),
            SupervisorExit::ResyncDrained | SupervisorExit::Stopping => unreachable!(),
        };
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
        let stopped = tokio::select! {
            stopped = sleep_or_stop(&probe.sync, delay) => stopped,
            _ = probe.sync.wait_for_resync() => {
                if drain_before_resync(&probe, &policy).await {
                    let epoch = prepare_staged_rebuild(&probe, None).await;
                    already_verified = finish_staged_rebuild(&probe, &cfg, &policy, epoch).await;
                    continue;
                }
                probe.sync.finish_resync();
                tracing::error!(
                    event = "sync_resync_aborted",
                    "the drain did not finish; serving replica and queued work were kept"
                );
                false
            }
        };
        if stopped {
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
    let push_started = tokio::time::Instant::now();
    let result = tokio::time::timeout(policy.budgets.shutdown.duration(), async {
        let _w = probe.write_mutex.lock().await;
        Engine::new(db, budgets).push().await
    })
    .await;
    record_push_duration(&probe.metrics, push_started);
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
            // This handle is already published and verified. Reporting a
            // fresh build here would push a ready replica back through
            // verifying, which makes reads fail closed for no reason. An
            // operator rebuild never takes this path; it uses staged_resync
            // after the pending work has drained.
            probe.sync.apply(SyncEvent::Heartbeat { at: unix_now() });
            return Some(db);
        }
        match replica_header_is_invalid(&cfg.replica_path) {
            Ok(true) => match quarantine_replica(&cfg.replica_path) {
                Ok(true) => {
                    tracing::error!(
                        event = "sync_replica_quarantined",
                        path = %cfg.replica_path,
                        "local replica header is invalid; rebuilding"
                    );
                    probe
                        .sync
                        .apply(SyncEvent::RebuildStarted { at: unix_now() });
                    continue;
                }
                Ok(false) => {}
                Err(error) => tracing::error!(
                    event = "sync_replica_quarantine_failed",
                    error = %error,
                    "could not quarantine local replica with an invalid header"
                ),
            },
            Ok(false) => {}
            Err(error) => {
                tracing::warn!(error = %error, "could not inspect local replica header")
            }
        }
        probe.conns.clear().await;
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
                let rebuild = should_quarantine_replica(&error);
                let transition = probe.sync.apply(SyncEvent::BuildFailed {
                    error: error.clone(),
                    at: unix_now(),
                });
                if rebuild {
                    match quarantine_replica(&cfg.replica_path) {
                        Ok(true) => {
                            tracing::error!(
                                event = "sync_replica_quarantined",
                                path = %cfg.replica_path,
                                "corrupt local replica quarantined; rebuilding"
                            );
                            probe
                                .sync
                                .apply(SyncEvent::RebuildStarted { at: unix_now() });
                            continue;
                        }
                        Ok(false) => {}
                        Err(quarantine_error) => {
                            tracing::error!(
                                event = "sync_replica_quarantine_failed",
                                error = %quarantine_error,
                                "could not quarantine corrupt local replica"
                            );
                        }
                    }
                }
                if retry_after(&probe.sync, &transition, policy).await {
                    return None;
                }
            }
        }
    }
}

/// Bring a replica to a known state before serving reads: converge with cloud,
/// ensure our tables, confirm the schema contract. `control` owns the epoch
/// and shutdown decision, so a staged candidate can be verified without
/// changing the health or readiness of the replica that is still serving.
/// Returns true only when the contract was verified.
async fn converge(
    probe: &DbState,
    control: &SyncStatus,
    db: &SyncDb,
    policy: &SyncPolicy,
    epoch: u64,
    already_verified: bool,
) -> bool {
    if already_verified && matches!(control.state(), SyncState::Ready) {
        return true;
    }
    probe
        .sync
        .apply(SyncEvent::VerifyStarted { at: unix_now() });
    loop {
        if control.stop_requested() || control.resync_epoch() != epoch {
            return false;
        }
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
                    return false;
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
                    return false;
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
                    return false;
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
                *probe.discovery_cache.write().await = None;
                *probe.paper_metadata_cache.write().await = None;
                return true;
            }
            Ok(Ok(Some(why))) => {
                probe.sync.apply(SyncEvent::ContractMismatch {
                    reason: why.clone(),
                    at: unix_now(),
                });
                tracing::error!("schema contract broken ({why}): data surfaces now fail closed");
                return false;
            }
            Ok(Err(error)) => {
                record_failure(&probe.metrics);
                let error = SyncError::new(state::classify(&error), error.to_string());
                let transition = probe.sync.apply(SyncEvent::VerifyFailed {
                    error,
                    at: unix_now(),
                });
                if retry_after(&probe.sync, &transition, policy).await {
                    return false;
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
                    return false;
                }
            }
        }
    }
}

/// Idle sleep is an optimization for a healthy replica, never a hiding place
/// for a failure. A degraded or blocked replica keeps probing so it can heal
/// without waiting for traffic that may never come.
#[cfg(test)]
fn may_enter_idle_sleep(
    state: SyncState,
    last_request: Timestamp,
    now: Timestamp,
    idle_after: Duration,
) -> bool {
    matches!(state, SyncState::Ready)
        && last_request != 0
        && now.saturating_sub(last_request) >= idle_after.as_secs()
}

/// Steady-state sync supervisor. External writers are rare, so there is no
/// periodic pull loop. The replica is converged on startup and refreshed on
/// demand via pull_now or pull_notify.
async fn supervise(probe: &DbState, db: &SyncDb, _idle_after: Duration, policy: &SyncPolicy) {
    let mut last_purge = tokio::time::Instant::now();
    let mut heartbeat_interval = tokio::time::interval(Duration::from_secs(15));
    heartbeat_interval.tick().await;
    loop {
        if probe.sync.stop_requested() {
            return;
        }
        tokio::select! {
            _ = probe.sync.wait_for_stop() => return,
            _ = probe.pull_notify.notified() => {
                let _ = pull_now_internal(probe, db, policy).await;
            }
            _ = heartbeat_interval.tick() => {
                let now = unix_now();
                probe.sync.apply(SyncEvent::Heartbeat { at: now });
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
                    match tokio::time::timeout(
                        policy.budgets.verify.duration(),
                        super::accounts::purge_expired_tokens(probe),
                    )
                    .await
                    {
                        Ok(Ok(0)) => {}
                        Ok(Ok(n)) => tracing::info!("purged {n} expired access tokens"),
                        Ok(Err(e)) => tracing::warn!("access token purge failed: {e}"),
                        Err(_) => tracing::warn!("access token purge exceeded its budget"),
                    }
                }
            }
        }
    }
}

/// Push retries are signalled by a failed request write. A slow or long-poll
/// pull therefore cannot block the write handler forever, and the retry path
/// does not issue an empty push on every pull timeout. The long fallback
/// rechecks pending state so a local commit recoverable after a restart is
/// not forgotten, but it does not push when no work is known to be pending.
async fn supervise_push(probe: DbState, db: SyncDb, policy: SyncPolicy, epoch: u64) {
    let mut resync = probe.sync.subscribe_resync();
    loop {
        if probe.sync.stop_requested() || probe.sync.resync_epoch() != epoch {
            return;
        }
        if probe.sync.push_pending() {
            tokio::time::sleep(PUSH_COALESCE).await;
            loop {
                if probe.sync.stop_requested() || probe.sync.resync_epoch() != epoch {
                    return;
                }
                probe.sync.apply(SyncEvent::PushStarted { at: unix_now() });
                let push_started = tokio::time::Instant::now();
                let result = {
                    let _w = probe.write_mutex.lock().await;
                    Engine::new(db.clone(), policy.budgets).push().await
                };
                record_push_duration(&probe.metrics, push_started);
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
                        let stopped = tokio::select! {
                            stopped = retry_after(&probe.sync, &transition, &policy) => stopped,
                            _ = resync.changed() => {
                                let _ = resync.borrow_and_update();
                                true
                            }
                        };
                        if stopped {
                            return;
                        }
                    }
                }
            }
        }
        tokio::select! {
            _ = probe.sync.wait_for_stop() => return,
            _ = resync.changed() => {
                let _ = resync.borrow_and_update();
                return;
            }
            _ = probe.push_notify.notified() => {}
            _ = tokio::time::sleep(PUSH_FALLBACK) => {}
        }
    }
}

/// A private probe for the candidate replica. It shares metrics so the pull
/// is observable, but owns its own status, pool, gate, write lock, and caches
/// so verification cannot retire a connection or change readiness for the
/// replica that is still serving.
fn staged_probe(probe: &DbState, db: SyncDb, cfg: &Config, policy: &SyncPolicy) -> DbState {
    let version = probe
        .bank_version
        .read()
        .map(|value| value.clone())
        .unwrap_or_default();
    DbState {
        sync: std::sync::Arc::new(SyncStatus::new(policy.clone())),
        db: std::sync::Arc::new(tokio::sync::RwLock::new(Some(db))),
        db_gate: std::sync::Arc::new(tokio::sync::Semaphore::new(cfg.db_max_concurrent)),
        conns: std::sync::Arc::new(super::ConnPool::new(cfg.db_max_concurrent)),
        metrics: std::sync::Arc::clone(&probe.metrics),
        cookie_secure: probe.cookie_secure,
        read_timeout_secs: probe.read_timeout_secs,
        write_mutex: std::sync::Arc::new(tokio::sync::Mutex::new(())),
        push_notify: std::sync::Arc::new(tokio::sync::Notify::new()),
        pull_notify: std::sync::Arc::new(tokio::sync::Notify::new()),
        limiter: std::sync::Arc::clone(&probe.limiter),
        bank_version: std::sync::Arc::new(std::sync::RwLock::new(version)),
        discovery_cache: std::sync::Arc::new(tokio::sync::RwLock::new(None)),
        paper_metadata_cache: std::sync::Arc::new(tokio::sync::RwLock::new(None)),
        media_base_url: std::sync::Arc::clone(&probe.media_base_url),
    }
}

async fn rollback_swap(cfg: &Config, displaced: &[(String, String)]) {
    if let Err(error) = quarantine_replica_files(&cfg.replica_path, "resync-failed") {
        tracing::error!(
            event = "sync_resync_rollback_quarantine_failed",
            error = %error,
            "could not move the failed replacement aside during rollback"
        );
    }
    restore_quarantined(displaced);
    // The serving handle and its pool were never retired, so the rollback is
    // only a file restore: no reader ever saw the failed replacement.
    tracing::warn!(
        event = "sync_resync_rollback",
        path = %cfg.replica_path,
        "serving replica was restored after a failed swap"
    );
}

/// Build and verify a fresh replica beside the serving one, then swap only
/// after the candidate is ready. A failed candidate leaves the serving replica
/// untouched. A failed swap restores the displaced files; the serving handle
/// and pool are only replaced once a prepared set of connections is ready.
async fn staged_resync(probe: &DbState, cfg: &Config, policy: &SyncPolicy, epoch: u64) -> bool {
    let staging = staging_replica_path(&cfg.replica_path, epoch);
    let mut stage_cfg = cfg.clone();
    stage_cfg.replica_path = staging.clone();
    let candidate = match build(&stage_cfg, policy).await {
        Ok(db) => db,
        Err(error) => {
            tracing::error!(
                event = "sync_resync_stage_failed",
                class = error.class.as_str(),
                error = %error.message,
                path = %staging,
                "could not build a staged replica"
            );
            return false;
        }
    };
    let stage_probe = staged_probe(probe, candidate.clone(), &stage_cfg, policy);
    stage_probe.conns.fill(&candidate, policy.budgets).await;
    let verified = converge(&stage_probe, &probe.sync, &candidate, policy, epoch, false).await;
    if !verified {
        tracing::error!(
            event = "sync_resync_stage_not_verified",
            path = %staging,
            "staged replica did not reach the contract; serving replica was kept"
        );
        *stage_probe.db.write().await = None;
        stage_probe.conns.clear().await;
        drop(stage_probe);
        drop(candidate);
        if let Err(error) = quarantine_replica_files(&staging, "resync-failed") {
            tracing::error!(event = "sync_resync_stage_quarantine_failed", error = %error);
        }
        return false;
    }
    let version = stage_probe
        .bank_version
        .read()
        .map(|value| value.clone())
        .unwrap_or_default();

    drop(stage_probe);
    drop(candidate);

    if probe.db.read().await.is_none() {
        tracing::error!(
            event = "sync_resync_no_serving_replica",
            "cannot stage a swap without a serving replica"
        );
        return false;
    }
    let _guard = probe.write_mutex.lock().await;
    if probe.sync.stop_requested() || probe.sync.resync_epoch() != epoch {
        return false;
    }

    // Only the files move here. The published handle and its pool stay live:
    // the displaced main file and sidecars keep serving under their new names
    // until the prepared replacement is installed below.
    let displaced = match quarantine_replica_files(&cfg.replica_path, "resync-superseded") {
        Ok(files) => files,
        Err(error) => {
            record_failure(&probe.metrics);
            tracing::error!(
                event = "sync_resync_displace_failed",
                error = %error,
                "could not move the serving replica aside"
            );
            return false;
        }
    };

    let _promoted = match promote_staged_replica(&staging, &cfg.replica_path) {
        Ok(files) => files,
        Err(error) => {
            record_failure(&probe.metrics);
            tracing::error!(event = "sync_resync_promote_failed", error = %error);
            rollback_swap(cfg, &displaced).await;
            return false;
        }
    };
    let final_db = match build(cfg, policy).await {
        Ok(db) => db,
        Err(error) => {
            record_failure(&probe.metrics);
            tracing::error!(
                event = "sync_resync_final_build_failed",
                class = error.class.as_str(),
                error = %error.message,
                path = %cfg.replica_path,
                "could not reopen the promoted replica"
            );
            rollback_swap(cfg, &displaced).await;
            if let Err(error) = quarantine_replica_files(&cfg.replica_path, "resync-failed") {
                tracing::error!(event = "sync_resync_promoted_quarantine_failed", error = %error);
            }
            return false;
        }
    };

    // Fill a replacement pool before touching the published handle. The swap
    // itself is then two in-memory assignments under the replica write lock,
    // so readers never see an empty handle or an unprimed pool.
    let (generation, replacement_conns) = match probe.conns.prepare(&final_db, policy.budgets).await
    {
        Ok(prepared) => prepared,
        Err(error) => {
            record_failure(&probe.metrics);
            tracing::error!(
                event = "sync_resync_pool_prepare_failed",
                class = error.class.as_str(),
                error = %error.message,
                "could not open replacement connections"
            );
            drop(final_db);
            rollback_swap(cfg, &displaced).await;
            if let Err(error) = quarantine_replica_files(&cfg.replica_path, "resync-failed") {
                tracing::error!(event = "sync_resync_promoted_quarantine_failed", error = %error);
            }
            return false;
        }
    };
    {
        let mut published = probe.db.write().await;
        probe
            .conns
            .install(&final_db, generation, replacement_conns)
            .await;
        *published = Some(final_db);
    }
    if let Ok(mut stored) = probe.bank_version.write() {
        *stored = version;
    }
    *probe.discovery_cache.write().await = None;
    *probe.paper_metadata_cache.write().await = None;
    let now = unix_now();
    probe.sync.clear_pending_for_rebuild(now);
    probe.sync.apply(SyncEvent::Heartbeat { at: now });
    probe.sync.apply(SyncEvent::PullSucceeded {
        changes: true,
        at: now,
    });
    probe.sync.apply(SyncEvent::ContractVerified { at: now });
    tracing::warn!(
        event = "sync_resync_swapped",
        epoch,
        path = %cfg.replica_path,
        "verified staged replica replaced the serving replica"
    );
    true
}

/// Ask the supervisor to pause writes, drain committed local work to Turso,
/// then build a fresh replica beside the serving one and swap it in. The call
/// is single-flight and gated. It returns `false` when a rebuild is already
/// queued, not when the rebuild failed; the outcome is reported in the
/// supervisor's logs and status fields. The epoch is still the active one when
/// this returns, so the push task can finish the drain.
pub async fn request_resync(probe: &DbState) -> Result<bool, crate::error::AppError> {
    if !probe.sync.policy().resync_enabled {
        return Err(crate::error::AppError::Conflict(
            "full resync is disabled; set SYNC_RESYNC_ENABLED=1 on this process".to_string(),
        ));
    }
    // Take the write lock before pausing writes. A writer already inside the
    // critical section finishes and records its pending work before this call
    // returns, so the drain cannot miss an in-flight commit.
    let _guard = probe.write_mutex.lock().await;
    if !probe.sync.request_resync() {
        return Ok(false);
    }
    tracing::warn!(
        event = "sync_resync_requested",
        epoch = probe.sync.resync_epoch(),
        pending_operations = probe.sync.health().pending_operations,
        pending_bytes = probe.sync.health().pending_bytes,
        "operator requested a drain-first staged full replica rebuild"
    );
    Ok(true)
}

/// On-demand pull. Pulls latest changes from Turso cloud, updates schema and bank version if
/// changes occurred, and returns whether new changes were pulled.
pub async fn pull_now(probe: &DbState) -> Result<bool, crate::error::AppError> {
    let Some(db) = probe.db.read().await.clone() else {
        return Err(crate::error::AppError::DbUnavailable("sync"));
    };
    let policy = probe.sync.policy().clone();
    pull_now_internal(probe, &db, &policy).await
}

async fn pull_now_internal(
    probe: &DbState,
    db: &SyncDb,
    policy: &SyncPolicy,
) -> Result<bool, crate::error::AppError> {
    let _guard = probe.write_mutex.lock().await;
    probe.sync.apply(SyncEvent::PullStarted { at: unix_now() });
    let started = tokio::time::Instant::now();
    let result = Engine::new(db.clone(), policy.budgets).pull().await;
    probe.metrics.last_pull_duration_ms.store(
        started.elapsed().as_millis().min(u64::MAX as u128) as u64,
        std::sync::atomic::Ordering::Relaxed,
    );
    probe
        .metrics
        .last_pull_unix
        .store(unix_now(), std::sync::atomic::Ordering::Relaxed);
    match result {
        Ok(had) => {
            record_pull(&probe.metrics, had);
            probe.sync.apply(SyncEvent::PullSucceeded {
                changes: had,
                at: unix_now(),
            });
            if had {
                recheck_contract(probe, policy).await;
                refresh_bank_version(probe, db).await;
            }
            Ok(had)
        }
        Err(error) => {
            record_failure(&probe.metrics);
            probe.sync.apply(SyncEvent::PullFailed {
                error: error.clone(),
                at: unix_now(),
            });
            Err(crate::error::AppError::Upstream(error.message))
        }
    }
}

/// Wake a sleeping replica. Fast and in-memory: client reads do not wait for
/// cloud network pulls.
pub(crate) async fn wake_if_sleeping(s: &DbState) -> Result<(), crate::error::AppError> {
    if s.sync.stop_requested() {
        return Err(crate::error::AppError::DbUnavailable("sync"));
    }
    if s.sync.sleeping() {
        s.sync.apply(SyncEvent::SleepEnded { at: unix_now() });
    }
    Ok(())
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
    use std::{sync::Arc, time::Duration};

    /// A serving replica whose operator gate is open. The default gate stays
    /// closed everywhere else so a test cannot accidentally rely on it.
    async fn resync_state() -> crate::state::DbState {
        let mut s = db_state(replica().await);
        let mut policy = s.sync.policy().clone();
        policy.resync_enabled = true;
        s.sync = Arc::new(super::SyncStatus::verified(policy));
        s
    }

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

    /// On-demand pull verification: the replica pulls when notified via
    /// pull_notify without needing a continuous background loop.
    #[tokio::test]
    async fn the_replica_is_pulled_on_demand() {
        let s = db_state(replica().await);
        let db = s.db.read().await.clone().expect("replica");
        let policy = s.sync.policy().clone();
        let task = tokio::spawn({
            let probe = s.clone();
            async move {
                super::supervise(&probe, &db, std::time::Duration::from_secs(300), &policy).await
            }
        });
        s.pull_notify.notify_one();
        tokio::time::sleep(std::time::Duration::from_millis(150)).await;
        task.abort();
        assert!(
            s.metrics
                .last_pull_unix
                .load(std::sync::atomic::Ordering::Relaxed)
                > 0,
            "an on-demand pull signal must trigger a pull"
        );
    }

    #[tokio::test]
    async fn shutdown_attempts_one_bounded_push_for_pending_work() {
        let s = db_state(replica().await);
        let mut policy = super::SyncPolicy::default();
        policy.budgets.push = super::Budget::new(Duration::from_millis(50));
        s.sync.mark_write_committed(1, 1);

        super::final_push_if_pending(&s, &policy).await;

        assert!(s.sync.push_pending(), "failed shutdown push stays pending");
        assert_eq!(
            s.metrics
                .push_count
                .load(std::sync::atomic::Ordering::Relaxed),
            1,
            "shutdown makes one bounded push attempt"
        );
    }

    #[test]
    fn only_a_ready_replica_enters_idle_sleep() {
        let idle = Duration::from_secs(300);
        assert!(super::may_enter_idle_sleep(
            super::SyncState::Ready,
            1_000,
            1_300,
            idle
        ));
        assert!(!super::may_enter_idle_sleep(
            super::SyncState::Degraded(super::DegradedReason::Failure(
                super::ErrorClass::TransientNetwork
            )),
            1_000,
            1_300,
            idle
        ));
        assert!(!super::may_enter_idle_sleep(
            super::SyncState::Blocked(super::BlockedReason::Auth),
            1_000,
            1_300,
            idle
        ));
        assert!(
            !super::may_enter_idle_sleep(super::SyncState::Ready, 0, 1_300, idle),
            "no request may not be mistaken for an idle window"
        );
        assert!(
            !super::may_enter_idle_sleep(super::SyncState::Ready, 1_000, 1_299, idle),
            "the window must actually be spent"
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

    #[test]
    fn only_corrupt_local_storage_errors_request_quarantine() {
        assert!(super::should_quarantine_replica(&super::SyncError::new(
            super::ErrorClass::LocalStorage,
            "database is corrupt",
        )));
        assert!(!super::should_quarantine_replica(&super::SyncError::new(
            super::ErrorClass::LocalStorage,
            "permission denied",
        )));
        assert!(!super::should_quarantine_replica(&super::SyncError::new(
            super::ErrorClass::Auth,
            "database is corrupt",
        )));
    }

    #[test]
    fn invalid_replica_header_is_detected_without_rejecting_empty_bootstrap() {
        let base = std::env::temp_dir().join(format!(
            "utmelab-sync-header-{}-{}",
            std::process::id(),
            super::unix_now()
        ));
        let path = base.to_string_lossy().into_owned();
        std::fs::write(&path, b"this is not sqlite").expect("create invalid fixture");
        assert!(super::replica_header_is_invalid(&path).expect("inspect invalid fixture"));
        std::fs::write(&path, []).expect("empty fixture");
        assert!(!super::replica_header_is_invalid(&path).expect("inspect empty fixture"));
        std::fs::remove_file(path).expect("remove header fixture");
    }

    #[test]
    fn corrupt_replica_files_are_quarantined_without_deletion() {
        let base = std::env::temp_dir().join(format!(
            "utmelab-sync-rebuild-{}-{}",
            std::process::id(),
            super::unix_now()
        ));
        let path = base.to_string_lossy().into_owned();
        std::fs::write(&path, b"corrupt").expect("create replica fixture");
        for suffix in ["-wal", "-shm", "-log", "-changes", "-info", "-wal-revert"] {
            std::fs::write(format!("{path}{suffix}"), suffix.as_bytes())
                .expect("create replica sidecar fixture");
        }

        assert!(super::quarantine_replica(&path).expect("quarantine fixture"));
        assert!(!std::path::Path::new(&path).exists());
        for suffix in ["-wal", "-shm", "-log", "-changes", "-info", "-wal-revert"] {
            assert!(!std::path::Path::new(&format!("{path}{suffix}")).exists());
        }

        let prefix = format!("{}.corrupt-", path);
        for entry in std::fs::read_dir(std::env::temp_dir()).expect("read temp directory") {
            let entry = entry.expect("read quarantine entry");
            let name = entry.path().to_string_lossy().into_owned();
            if name.starts_with(&prefix) {
                std::fs::remove_file(entry.path()).expect("remove quarantine fixture");
            }
        }
    }

    #[test]
    fn orphaned_sidecars_are_quarantined_without_a_main_replica() {
        let base = std::env::temp_dir().join(format!(
            "utmelab-sync-sidecar-{}-{}",
            std::process::id(),
            super::unix_now()
        ));
        let path = base.to_string_lossy().into_owned();
        let wal = format!("{path}-wal");
        std::fs::write(&wal, b"wal").expect("create orphaned wal fixture");

        assert!(super::quarantine_replica(&path).expect("quarantine sidecar"));
        assert!(!std::path::Path::new(&wal).exists());

        let prefix = format!("{}.corrupt-", path);
        for entry in std::fs::read_dir(std::env::temp_dir()).expect("read temp directory") {
            let entry = entry.expect("read quarantine entry");
            let name = entry.path().to_string_lossy().into_owned();
            if name.starts_with(&prefix) {
                std::fs::remove_file(entry.path()).expect("remove quarantine fixture");
            }
        }
    }

    #[tokio::test]
    async fn wake_pull_failure_serves_degraded_reads_if_content_fresh() {
        use super::SyncEvent;
        use crate::testing::{db_state, replica};
        let db = replica().await;
        let s = db_state(db);
        let now = super::unix_now();
        s.sync.apply(SyncEvent::Heartbeat { at: now });
        s.sync.apply(SyncEvent::PullSucceeded {
            changes: false,
            at: now,
        });
        s.sync.apply(SyncEvent::SleepStarted { at: now });

        assert!(s.sync.sleeping());
        assert!(s.sync.readiness().allows_public_reads());

        let result = super::wake_if_sleeping(&s).await;
        assert!(
            result.is_ok(),
            "wake failure should not block fresh content reads"
        );
        assert!(!s.sync.sleeping());
        assert!(s.sync.readiness().allows_public_reads());
    }

    fn stale_paper_metadata() -> std::sync::Arc<crate::state::PaperMetadata> {
        std::sync::Arc::new(crate::state::PaperMetadata {
            exam: crate::core::models::Exam {
                code: "STALE".into(),
                name: "Stale".into(),
                countries: vec![],
                status: "live".into(),
                has_full_paper: None,
                subjects_required: None,
                duration_minutes: None,
                rules: vec![],
            },
            subject: crate::core::models::Subject {
                slug: "stale".into(),
                exam: "STALE".into(),
                name: "Stale".into(),
                order: 0,
                is_compulsory: false,
                objective_paper_questions: None,
                countries: vec![],
                syllabus_exam: None,
                syllabus_subject: None,
            },
            blueprints: vec![],
            syllabus: vec![],
        })
    }

    #[tokio::test]
    async fn request_resync_pauses_writes_before_the_epoch_advances() {
        let s = resync_state().await;
        s.sync.mark_write_committed(3, 96);
        *s.bank_version.write().expect("bank lock") = "stale".to_string();
        *s.discovery_cache.write().await =
            Some(("stale".to_string(), std::sync::Arc::new(Vec::new())));
        *s.paper_metadata_cache.write().await = Some((
            "stale".to_string(),
            "STALE".to_string(),
            "stale".to_string(),
            stale_paper_metadata(),
        ));
        let before = s.sync.resync_epoch();

        assert!(super::request_resync(&s).await.expect("first resync"));
        assert!(!super::request_resync(&s).await.expect("second resync"));
        assert_eq!(
            s.sync.resync_epoch(),
            before,
            "the push task must stay alive until the drain succeeds"
        );
        assert!(s.sync.resync_pending());
        assert!(
            s.sync.resync_draining(),
            "new writes pause while committed work drains"
        );
        assert!(
            s.db.read().await.is_some(),
            "requesting a rebuild must not take the serving replica down"
        );
        assert!(
            s.sync.readiness().allows_public_reads(),
            "staging happens before any readiness change"
        );
        assert!(s.discovery_cache.read().await.is_some());
        assert!(s.paper_metadata_cache.read().await.is_some());
        assert_eq!(s.bank_version.read().expect("bank lock").as_str(), "stale");

        let health = s.sync.health();
        assert_eq!(health.pending_operations, 3);
        assert_eq!(health.pending_bytes, 96);
        assert!(health.push_pending);

        assert_eq!(s.sync.begin_resync_epoch(), before + 1);
        s.sync.finish_resync();
        assert!(!s.sync.resync_pending());
        assert!(!s.sync.resync_draining());
    }

    #[tokio::test]
    async fn requesting_a_rebuild_waits_for_an_in_flight_write() {
        let s = resync_state().await;
        let in_flight = s.write_mutex.lock().await;
        let requester = s.clone();
        let handle = tokio::spawn(async move { super::request_resync(&requester).await });
        tokio::time::sleep(Duration::from_millis(10)).await;
        assert!(
            !handle.is_finished(),
            "the request must not pause writes inside an active write"
        );

        s.sync.mark_write_committed(1, 1);
        drop(in_flight);
        assert!(handle.await.expect("join").expect("gate is open"));
        assert_eq!(s.sync.health().pending_operations, 1);
        assert!(
            s.sync.resync_draining(),
            "the in-flight commit is now the closed set the drain must clear"
        );
        s.sync.finish_resync();
    }

    #[tokio::test]
    async fn drain_waits_for_committed_local_work_to_clear() {
        let s = db_state(replica().await);
        s.sync.mark_write_committed(2, 64);
        let policy = s.sync.policy().clone();
        let clearer = s.clone();
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(25)).await;
            clearer.sync.apply(super::SyncEvent::PushSucceeded {
                at: super::unix_now(),
            });
        });

        let drained = tokio::time::timeout(Duration::from_secs(2), async {
            super::drain_before_resync(&s, &policy).await
        })
        .await
        .expect("drain finishes inside the test budget");
        assert!(drained, "a completed push must satisfy the drain");
        assert!(!s.sync.push_pending());
    }

    #[tokio::test]
    async fn drain_timeout_aborts_without_clearing_pending_work() {
        let s = db_state(replica().await);
        s.sync.mark_write_committed(2, 64);
        let mut policy = s.sync.policy().clone();
        policy.resync_drain = Duration::from_millis(40);

        let drained = tokio::time::timeout(Duration::from_secs(2), async {
            super::drain_before_resync(&s, &policy).await
        })
        .await
        .expect("drain timeout is bounded");
        assert!(!drained, "an unmovable push must abort the rebuild");
        let health = s.sync.health();
        assert_eq!(health.pending_operations, 2);
        assert_eq!(health.pending_bytes, 64);
        assert!(health.push_pending);
    }

    #[tokio::test]
    async fn a_full_resync_is_refused_while_the_operator_gate_is_closed() {
        let s = db_state(replica().await);
        assert!(!s.sync.policy().resync_enabled);
        let before = s.sync.resync_epoch();
        let error = super::request_resync(&s)
            .await
            .expect_err("a closed gate refuses the operation");
        let crate::error::AppError::Conflict(message) = error else {
            panic!("expected a conflict, got {error:?}");
        };
        assert!(message.contains("SYNC_RESYNC_ENABLED"), "{message}");
        assert_eq!(s.sync.resync_epoch(), before);
        assert!(!s.sync.resync_pending());
    }

    #[test]
    fn a_staged_path_never_collides_with_the_serving_path() {
        let path = "/var/lib/utmelab-api/sync.db";
        let staging = super::staging_replica_path(path, 7);
        assert!(staging.starts_with(path));
        assert!(staging.contains(".resync-7-"));
        assert_ne!(staging, path);
        assert!(!super::replica_files(&staging).contains(&path.to_string()));
    }

    #[test]
    fn a_verified_staged_replica_promotes_every_artifact() {
        let base = std::env::temp_dir().join(format!(
            "utmelab-sync-promote-{}-{}",
            std::process::id(),
            super::unix_now()
        ));
        let staging = format!("{}.resync-9", base.to_string_lossy());
        let serving = base.to_string_lossy().into_owned();
        std::fs::write(&staging, b"database").expect("staged replica");
        std::fs::write(format!("{staging}-wal"), b"wal").expect("staged wal");

        let moved = super::promote_staged_replica(&staging, &serving).expect("promotion");
        assert_eq!(moved.len(), 2);
        assert_eq!(std::fs::read(&serving).expect("promoted"), b"database");
        assert_eq!(
            std::fs::read(format!("{serving}-wal")).expect("promoted wal"),
            b"wal"
        );
        assert!(!std::path::Path::new(&staging).exists());

        for entry in std::fs::read_dir(std::env::temp_dir()).expect("read temp directory") {
            let path = entry.expect("entry").path();
            let name = path.to_string_lossy();
            if name.starts_with(&format!("{serving}.resync-9"))
                || name == serving
                || name.starts_with(&format!("{serving}-wal"))
            {
                let _ = std::fs::remove_file(path);
            }
        }
    }

    /// A root restart must reuse a published handle without reporting a new
    /// build. `BuildSucceeded` would move a ready replica back to verifying
    /// and fail reads even though nothing changed on disk.
    #[tokio::test]
    async fn opening_a_published_replica_keeps_the_ready_state() {
        let s = resync_state().await;
        let published = s.db.read().await.clone().expect("replica");
        let policy = s.sync.policy().clone();

        let opened = super::open(&s, &crate::config::Config::default(), &policy)
            .await
            .expect("published replica is reused");

        assert!(Arc::ptr_eq(&opened, &published));
        assert!(matches!(s.sync.state(), super::SyncState::Ready));
    }

    #[tokio::test]
    async fn a_resync_retires_a_waiting_push_task() {
        let s = db_state(replica().await);
        s.sync.clear_pending_for_rebuild(super::unix_now());
        let db = s.db.read().await.clone().expect("replica");
        let policy = s.sync.policy().clone();
        let epoch = s.sync.resync_epoch();
        let handle = tokio::spawn({
            let probe = s.clone();
            async move { super::supervise_push(probe, db, policy, epoch).await }
        });

        tokio::time::sleep(Duration::from_millis(25)).await;
        assert!(!handle.is_finished(), "the push task should be waiting");
        assert!(s.sync.request_resync());
        assert!(
            !handle.is_finished(),
            "the push task must survive until the drain advances the epoch"
        );
        s.sync.begin_resync_epoch();

        let joined = tokio::time::timeout(Duration::from_millis(500), handle)
            .await
            .expect("push task retires when the epoch changes");
        assert!(joined.is_ok(), "push task should exit cleanly");
    }
}
