//! One sync state machine, one health snapshot, one readiness rule.
//!
//! The supervisor is the only writer. It turns an event into a new state with
//! [`SyncStatus::apply`]; handlers and middleware only read. The transition
//! function is pure, so every state and event pair is covered by a table test
//! instead of being discovered in production.
//!
//! Readiness is derived from state, freshness, and the supervisor heartbeat.
//! It is never a separate boolean that a handler can set.

use std::{
    sync::{Mutex, MutexGuard},
    time::Duration,
};

use super::{
    policy::{classify_app, ErrorClass, FreshnessPolicy, SyncError, SyncPolicy, Timestamp},
    unix_now,
};

/// What the sync subsystem is doing. Every value has one readiness answer.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SyncState {
    /// Process is up, no replica handle yet.
    Starting,
    /// The replica is being built or opened.
    Bootstrapping,
    /// First pull, local schema work, and contract check are running.
    Verifying,
    /// Replica is open, verified, and within the freshness budget.
    Ready,
    /// Last trusted replica is serving, but a sync attempt failed or data is
    /// older than the ideal threshold.
    Degraded(DegradedReason),
    /// The replica cannot be trusted or progress cannot be made.
    Blocked(BlockedReason),
    /// Shutdown has begun. New writes are refused.
    Stopping,
    /// No more work.
    Stopped,
}

impl SyncState {
    pub const fn label(self) -> &'static str {
        match self {
            Self::Starting => "starting",
            Self::Bootstrapping => "bootstrapping",
            Self::Verifying => "verifying",
            Self::Ready => "ready",
            Self::Degraded(_) => "degraded",
            Self::Blocked(_) => "blocked",
            Self::Stopping => "stopping",
            Self::Stopped => "stopped",
        }
    }

    pub const fn blocked_reason(self) -> Option<BlockedReason> {
        match self {
            Self::Blocked(reason) => Some(reason),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DegradedReason {
    Failure(ErrorClass),
    NoSuccessfulPull,
    ContentStale,
    AuthStale,
    PushPending,
}

impl DegradedReason {
    pub const fn label(self) -> &'static str {
        match self {
            Self::Failure(class) => class.as_str(),
            Self::NoSuccessfulPull => "no_successful_pull",
            Self::ContentStale => "content_stale",
            Self::AuthStale => "auth_stale",
            Self::PushPending => "push_pending",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BlockedReason {
    NotReady,
    MissingReplica,
    SchemaMismatch,
    Auth,
    Configuration,
    LocalStorage,
    RebuildRequired,
    SupervisorStalled,
    Stopping,
}

impl BlockedReason {
    pub const fn label(self) -> &'static str {
        match self {
            Self::NotReady => "not_ready",
            Self::MissingReplica => "missing_replica",
            Self::SchemaMismatch => "schema_mismatch",
            Self::Auth => "auth",
            Self::Configuration => "configuration",
            Self::LocalStorage => "local_storage",
            Self::RebuildRequired => "rebuild_required",
            Self::SupervisorStalled => "supervisor_stalled",
            Self::Stopping => "stopping",
        }
    }

    pub const fn from_class(class: ErrorClass) -> Self {
        match class {
            ErrorClass::Auth => Self::Auth,
            ErrorClass::Configuration => Self::Configuration,
            ErrorClass::LocalStorage => Self::LocalStorage,
            ErrorClass::Schema => Self::SchemaMismatch,
            _ => Self::NotReady,
        }
    }
}

/// The health facts readiness needs. Timestamps are Unix seconds.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SyncHealth {
    pub last_attempt_pull_unix: Timestamp,
    pub last_success_pull_unix: Timestamp,
    pub last_attempt_push_unix: Timestamp,
    pub last_success_push_unix: Timestamp,
    pub last_error_unix: Timestamp,
    pub last_error_class: Option<ErrorClass>,
    pub consecutive_failures: u32,
    pub consecutive_push_failures: u32,
    pub heartbeat_unix: Timestamp,
    /// Local work committed since the last successful push. These are
    /// process-local counters. They are a lower bound after a restart, so the
    /// push supervisor still performs one boot push and retries on the
    /// fallback interval until a push succeeds.
    pub pending_operations: u64,
    pub pending_bytes: u64,
    pub push_pending: bool,
}

impl SyncHealth {
    pub const fn staleness_secs(&self, now: Timestamp) -> u64 {
        if self.last_success_pull_unix == 0 {
            return u64::MAX;
        }
        now.saturating_sub(self.last_success_pull_unix)
    }

    pub const fn heartbeat_age_secs(&self, now: Timestamp) -> u64 {
        if self.heartbeat_unix == 0 {
            return u64::MAX;
        }
        now.saturating_sub(self.heartbeat_unix)
    }
}

/// Events the supervisor may apply. Every event carries its own time so the
/// reducer never reads a clock and tests are deterministic.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SyncEvent {
    BuildStarted { at: Timestamp },
    BuildSucceeded { at: Timestamp },
    BuildFailed { error: SyncError, at: Timestamp },
    PullStarted { at: Timestamp },
    PullSucceeded { changes: bool, at: Timestamp },
    PullFailed { error: SyncError, at: Timestamp },
    PushStarted { at: Timestamp },
    PushSucceeded { at: Timestamp },
    PushFailed { error: SyncError, at: Timestamp },
    VerifyStarted { at: Timestamp },
    ContractVerified { at: Timestamp },
    ContractMismatch { reason: String, at: Timestamp },
    VerifyFailed { error: SyncError, at: Timestamp },
    Heartbeat { at: Timestamp },
    Stopping { at: Timestamp },
    Stopped { at: Timestamp },
}

impl SyncEvent {
    pub const fn at(&self) -> Timestamp {
        match self {
            Self::BuildStarted { at }
            | Self::BuildSucceeded { at }
            | Self::BuildFailed { at, .. }
            | Self::PullStarted { at }
            | Self::PullSucceeded { at, .. }
            | Self::PullFailed { at, .. }
            | Self::PushStarted { at }
            | Self::PushSucceeded { at }
            | Self::PushFailed { at, .. }
            | Self::VerifyStarted { at }
            | Self::ContractVerified { at }
            | Self::ContractMismatch { at, .. }
            | Self::VerifyFailed { at, .. }
            | Self::Heartbeat { at }
            | Self::Stopping { at }
            | Self::Stopped { at } => *at,
        }
    }

    fn failure(&self) -> Option<(&SyncError, Timestamp)> {
        match self {
            Self::BuildFailed { error, at }
            | Self::PullFailed { error, at }
            | Self::PushFailed { error, at }
            | Self::VerifyFailed { error, at } => Some((error, *at)),
            _ => None,
        }
    }
}

/// The retry the caller must schedule. The state machine does not sleep.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RetryInstruction {
    pub class: ErrorClass,
    pub delay: Duration,
}

/// One reducer result. `changed` is true when the state itself moved, not when
/// only health changed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Transition {
    pub state: SyncState,
    pub health: SyncHealth,
    pub retry: Option<RetryInstruction>,
    pub changed: bool,
    pub readiness: Readiness,
}

/// A transition the machine cannot express. Kept explicit so a future state
/// cannot be added without deciding its edges.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InvalidTransition {
    pub from: SyncState,
    pub event: &'static str,
}

/// Pure reducer. The jitter sample is supplied by the caller, which keeps this
/// function deterministic and testable while production still jitters.
pub fn transition(
    state: SyncState,
    health: &SyncHealth,
    event: &SyncEvent,
    policy: &SyncPolicy,
    jitter_sample: f64,
) -> Result<Transition, InvalidTransition> {
    let at = event.at();
    let mut next_state = state;
    let mut next_health = health.clone();
    let mut retry = None;

    if matches!(state, SyncState::Stopped) {
        return Ok(Transition {
            state: SyncState::Stopped,
            health: next_health,
            retry: None,
            changed: false,
            readiness: readiness(SyncState::Stopped, health, at, &policy.freshness),
        });
    }

    if let Some((error, at)) = event.failure() {
        next_health.last_error_unix = at;
        next_health.last_error_class = Some(error.class);
        match event {
            SyncEvent::PushFailed { .. } => {
                next_health.consecutive_push_failures =
                    next_health.consecutive_push_failures.saturating_add(1);
            }
            _ => {
                next_health.consecutive_failures =
                    next_health.consecutive_failures.saturating_add(1);
            }
        }
        let attempt = next_health
            .consecutive_failures
            .max(next_health.consecutive_push_failures)
            .max(1);
        retry = Some(RetryInstruction {
            class: error.class,
            delay: policy.retry_delay(attempt, error.class, jitter_sample),
        });
    }

    match event {
        SyncEvent::BuildStarted { .. } => {
            next_state = SyncState::Bootstrapping;
        }
        SyncEvent::BuildSucceeded { .. } => {
            next_health.heartbeat_unix = at;
            next_state = SyncState::Verifying;
        }
        SyncEvent::BuildFailed { error, .. } => {
            next_state = if error.class.is_permanent() {
                SyncState::Blocked(BlockedReason::from_class(error.class))
            } else {
                SyncState::Bootstrapping
            };
        }
        SyncEvent::PullStarted { .. } => {
            next_health.last_attempt_pull_unix = at;
        }
        SyncEvent::PullSucceeded { .. } => {
            next_health.last_success_pull_unix = at;
            next_health.consecutive_failures = 0;
            next_health.last_error_class = None;
            next_state = match state {
                // A successful pull does not verify the schema. Only an
                // explicit contract event may cross this line.
                SyncState::Verifying
                | SyncState::Blocked(_)
                | SyncState::Starting
                | SyncState::Bootstrapping => state,
                SyncState::Ready | SyncState::Degraded(_) => SyncState::Ready,
                SyncState::Stopping | SyncState::Stopped => state,
            };
        }
        SyncEvent::PullFailed { error, .. } => {
            next_state = match state {
                SyncState::Stopping | SyncState::Stopped => state,
                SyncState::Blocked(reason) => SyncState::Blocked(reason),
                _ if error.class.is_permanent() => {
                    SyncState::Blocked(BlockedReason::from_class(error.class))
                }
                SyncState::Ready | SyncState::Degraded(_) => {
                    SyncState::Degraded(DegradedReason::Failure(error.class))
                }
                SyncState::Starting | SyncState::Bootstrapping | SyncState::Verifying => state,
            };
        }
        SyncEvent::PushStarted { .. } => {
            next_health.last_attempt_push_unix = at;
            next_health.push_pending = true;
        }
        SyncEvent::PushSucceeded { .. } => {
            next_health.last_success_push_unix = at;
            next_health.consecutive_push_failures = 0;
            next_health.pending_operations = 0;
            next_health.pending_bytes = 0;
            next_health.push_pending = false;
        }
        SyncEvent::PushFailed { .. } => {
            // Push failure changes write health, not read trust. The state
            // stays where it is so a read-only replica can still serve.
            next_health.push_pending = true;
            next_health.pending_operations = next_health.pending_operations.max(1);
            next_state = state;
        }
        SyncEvent::VerifyStarted { .. } => {
            if !matches!(state, SyncState::Stopping | SyncState::Stopped) {
                next_state = SyncState::Verifying;
            }
        }
        SyncEvent::ContractVerified { .. } => {
            next_health.heartbeat_unix = at;
            if !matches!(state, SyncState::Stopping | SyncState::Stopped) {
                next_state = SyncState::Ready;
            }
        }
        SyncEvent::ContractMismatch { .. } => {
            next_state = SyncState::Blocked(BlockedReason::SchemaMismatch);
        }
        SyncEvent::VerifyFailed { error, .. } => {
            next_state = if error.class.is_permanent() {
                SyncState::Blocked(BlockedReason::from_class(error.class))
            } else {
                state
            };
        }
        SyncEvent::Heartbeat { .. } => {
            next_health.heartbeat_unix = at;
        }
        SyncEvent::Stopping { .. } => {
            next_state = SyncState::Stopping;
        }
        SyncEvent::Stopped { .. } => {
            next_state = SyncState::Stopped;
        }
    }

    let changed = next_state != state;
    Ok(Transition {
        state: next_state,
        health: next_health.clone(),
        retry,
        changed,
        readiness: readiness(next_state, &next_health, at, &policy.freshness),
    })
}

/// The single readiness answer. `Ready` means content and credentials are
/// both inside budget. A degraded replica can still serve content while its
/// credential view is too old.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Readiness {
    Ready,
    Degraded {
        content_fresh: bool,
        auth_fresh: bool,
        reason: DegradedReason,
    },
    Blocked(BlockedReason),
}

impl Readiness {
    pub const fn http_ready(self) -> bool {
        match self {
            Self::Ready => true,
            Self::Degraded { content_fresh, .. } => content_fresh,
            Self::Blocked(_) => false,
        }
    }

    pub const fn allows_public_reads(self) -> bool {
        self.http_ready()
    }

    pub const fn allows_keyed_reads(self) -> bool {
        match self {
            Self::Ready => true,
            Self::Degraded {
                content_fresh,
                auth_fresh,
                ..
            } => content_fresh && auth_fresh,
            Self::Blocked(_) => false,
        }
    }

    pub const fn allows_writes(self) -> bool {
        match self {
            Self::Ready => true,
            Self::Degraded { content_fresh, .. } => content_fresh,
            Self::Blocked(_) => false,
        }
    }

    pub const fn reason_label(self) -> &'static str {
        match self {
            Self::Ready => "ready",
            Self::Degraded { reason, .. } => reason.label(),
            Self::Blocked(reason) => reason.label(),
        }
    }
}

/// Readiness for one state and health snapshot. This is the only readiness
/// rule in the crate.
pub fn readiness(
    state: SyncState,
    health: &SyncHealth,
    now: Timestamp,
    freshness: &FreshnessPolicy,
) -> Readiness {
    match state {
        SyncState::Blocked(reason) => return Readiness::Blocked(reason),
        SyncState::Stopping | SyncState::Stopped => {
            return Readiness::Blocked(BlockedReason::Stopping)
        }
        SyncState::Starting | SyncState::Bootstrapping | SyncState::Verifying => {
            return Readiness::Blocked(BlockedReason::NotReady)
        }
        SyncState::Ready | SyncState::Degraded(_) => {}
    }

    if health.heartbeat_unix == 0
        || health
            .heartbeat_age_secs(now)
            .gt(&freshness.heartbeat_max_age.as_secs())
    {
        return Readiness::Blocked(BlockedReason::SupervisorStalled);
    }

    if health.last_success_pull_unix == 0 {
        return Readiness::Degraded {
            content_fresh: false,
            auth_fresh: false,
            reason: DegradedReason::NoSuccessfulPull,
        };
    }

    let age = health.staleness_secs(now);
    let content_fresh = age <= freshness.content_max_age.as_secs();
    let auth_fresh = age <= freshness.auth_max_age.as_secs();
    if content_fresh && auth_fresh && matches!(state, SyncState::Ready) {
        return Readiness::Ready;
    }

    let reason = match state {
        SyncState::Degraded(reason) => reason,
        _ if !content_fresh => DegradedReason::ContentStale,
        _ => DegradedReason::AuthStale,
    };
    Readiness::Degraded {
        content_fresh,
        auth_fresh,
        reason,
    }
}

/// Shared, interior-mutable sync status. All methods are short and never hold
/// the lock across an await.
pub struct SyncStatus {
    policy: SyncPolicy,
    inner: Mutex<Snapshot>,
    stop_notify: std::sync::Arc<tokio::sync::Notify>,
}

#[derive(Clone, Debug)]
struct Snapshot {
    state: SyncState,
    health: SyncHealth,
    next_wake_retry_unix: Timestamp,
    stopping: bool,
}

impl SyncStatus {
    pub fn new(policy: SyncPolicy) -> Self {
        let now = unix_now();
        Self {
            policy,
            inner: Mutex::new(Snapshot {
                state: SyncState::Starting,
                health: SyncHealth {
                    heartbeat_unix: now,
                    push_pending: true,
                    ..SyncHealth::default()
                },
                next_wake_retry_unix: 0,
                stopping: false,
            }),
            stop_notify: std::sync::Arc::new(tokio::sync::Notify::new()),
        }
    }

    /// A replica that is already verified, used by detached commands and test
    /// fixtures. It is explicit, not a default.
    pub fn verified(policy: SyncPolicy) -> Self {
        let now = unix_now();
        Self {
            policy,
            inner: Mutex::new(Snapshot {
                state: SyncState::Ready,
                health: SyncHealth {
                    last_success_pull_unix: now,
                    heartbeat_unix: now,
                    push_pending: true,
                    ..SyncHealth::default()
                },
                next_wake_retry_unix: 0,
                stopping: false,
            }),
            stop_notify: std::sync::Arc::new(tokio::sync::Notify::new()),
        }
    }

    /// A blocked fixture, used by tests that exercise fail-closed surfaces.
    pub fn blocked(policy: SyncPolicy, reason: BlockedReason) -> Self {
        let now = unix_now();
        Self {
            policy,
            inner: Mutex::new(Snapshot {
                state: SyncState::Blocked(reason),
                health: SyncHealth {
                    heartbeat_unix: now,
                    push_pending: true,
                    ..SyncHealth::default()
                },
                next_wake_retry_unix: 0,
                stopping: false,
            }),
            stop_notify: std::sync::Arc::new(tokio::sync::Notify::new()),
        }
    }

    pub fn policy(&self) -> &SyncPolicy {
        &self.policy
    }

    fn lock(&self) -> MutexGuard<'_, Snapshot> {
        // A panic while holding this lock must not poison readiness forever.
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn state(&self) -> SyncState {
        self.lock().state
    }

    pub fn health(&self) -> SyncHealth {
        self.lock().health.clone()
    }

    /// The process-local lower bound on unsent local work.
    pub fn pending_work(&self) -> super::policy::PendingWork {
        let health = self.health();
        super::policy::PendingWork::Known {
            operations: health.pending_operations,
            bytes: health.pending_bytes,
        }
    }

    pub fn push_pending(&self) -> bool {
        self.lock().health.push_pending
    }

    /// Record a local commit that has not yet reached the remote. The write
    /// path calls this while it still holds the write mutex, so concurrent
    /// writers cannot over-admit against a stale count.
    pub fn mark_write_committed(&self, operations: u64, bytes: u64) {
        if operations == 0 && bytes == 0 {
            return;
        }
        let mut snapshot = self.lock();
        snapshot.health.pending_operations = snapshot
            .health
            .pending_operations
            .saturating_add(operations);
        snapshot.health.pending_bytes = snapshot.health.pending_bytes.saturating_add(bytes);
        snapshot.health.push_pending = true;
    }

    pub fn begin_stop(&self) {
        self.apply(SyncEvent::Stopping { at: unix_now() });
        self.stop_notify.notify_waiters();
    }

    pub fn stop_requested(&self) -> bool {
        let snapshot = self.lock();
        snapshot.stopping || matches!(snapshot.state, SyncState::Stopping | SyncState::Stopped)
    }

    pub(crate) async fn wait_for_stop(&self) {
        if self.stop_requested() {
            return;
        }
        self.stop_notify.notified().await;
    }

    pub fn readiness(&self) -> Readiness {
        let snapshot = self.lock();
        readiness(
            snapshot.state,
            &snapshot.health,
            unix_now(),
            &self.policy.freshness,
        )
    }

    /// Apply one event and return the resulting transition. The caller uses
    /// the retry instruction and never invents a delay.
    pub fn apply(&self, event: SyncEvent) -> Transition {
        let mut snapshot = self.lock();
        let jitter = jitter_sample(event.at(), snapshot.health.consecutive_failures);
        let transition = transition(
            snapshot.state,
            &snapshot.health,
            &event,
            &self.policy,
            jitter,
        )
        .unwrap_or_else(|_| Transition {
            state: snapshot.state,
            health: snapshot.health.clone(),
            retry: None,
            changed: false,
            readiness: readiness(
                snapshot.state,
                &snapshot.health,
                event.at(),
                &self.policy.freshness,
            ),
        });

        let from = snapshot.state;
        snapshot.state = transition.state;
        snapshot.health = transition.health.clone();
        snapshot.stopping =
            snapshot.stopping || matches!(snapshot.state, SyncState::Stopping | SyncState::Stopped);

        if transition.changed {
            tracing::info!(
                event = "sync_state_changed",
                from = from.label(),
                to = transition.state.label(),
                readiness = transition.readiness.reason_label(),
                class = transition
                    .health
                    .last_error_class
                    .map(ErrorClass::as_str)
                    .unwrap_or("none"),
                "sync state changed"
            );
        } else if let Some((error, _)) = event.failure() {
            if transition.health.consecutive_failures == 1
                || transition.health.consecutive_push_failures == 1
            {
                tracing::warn!(
                    event = "sync_failure",
                    class = error.class.as_str(),
                    error = %error.message,
                    "sync attempt failed"
                );
            } else {
                tracing::debug!(
                    event = "sync_failure_repeat",
                    class = error.class.as_str(),
                    "sync attempt failed again"
                );
            }
        }

        transition
    }

    /// Wake throttling: a failed wake must not turn every request into a new
    /// remote attempt during an outage.
    pub fn wake_allowed(&self) -> bool {
        let snapshot = self.lock();
        unix_now() >= snapshot.next_wake_retry_unix
    }

    pub fn record_wake_failure(&self, error: &SyncError, at: Timestamp) -> Duration {
        let mut snapshot = self.lock();
        snapshot.state = SyncState::Degraded(DegradedReason::Failure(error.class));
        snapshot.health.last_error_unix = at;
        snapshot.health.last_error_class = Some(error.class);
        snapshot.health.consecutive_failures =
            snapshot.health.consecutive_failures.saturating_add(1);
        let attempt = snapshot.health.consecutive_failures.max(1);
        let delay = self
            .policy
            .retry_delay(attempt, error.class, jitter_sample(at, attempt));
        snapshot.next_wake_retry_unix = at.saturating_add(delay.as_secs());
        delay
    }

    pub fn record_wake_success(&self, changes: bool, at: Timestamp) {
        let mut snapshot = self.lock();
        snapshot.health.last_attempt_pull_unix = at;
        snapshot.health.last_success_pull_unix = at;
        snapshot.health.consecutive_failures = 0;
        snapshot.health.last_error_class = None;
        snapshot.next_wake_retry_unix = 0;
        if matches!(snapshot.state, SyncState::Degraded(_)) {
            snapshot.state = SyncState::Ready;
        }
        tracing::debug!(changes, "wake pull completed");
    }

    pub fn mark_blocked(&self, reason: BlockedReason) {
        let mut snapshot = self.lock();
        if snapshot.stopping || matches!(snapshot.state, SyncState::Stopping | SyncState::Stopped) {
            return;
        }
        let from = snapshot.state;
        snapshot.state = SyncState::Blocked(reason);
        if from != snapshot.state {
            tracing::warn!(
                event = "sync_state_changed",
                from = from.label(),
                to = "blocked",
                reason = reason.label(),
                "sync state changed"
            );
        }
    }
}

/// Deterministic jitter in `[0, 1)`. Using event time and the attempt count
/// avoids a random dependency while still separating attempts that would
/// otherwise retry in lockstep.
fn jitter_sample(at: Timestamp, attempt: u32) -> f64 {
    let mixed = at
        .wrapping_mul(6_364_136_223_846_793_005)
        .wrapping_add((attempt as u64).wrapping_mul(1_442_695_040_888_963_407));
    (mixed >> 11) as f64 / (1u64 << 53) as f64
}

/// Classify an application error at the boundary for callers that hold one.
pub fn classify(error: &crate::error::AppError) -> ErrorClass {
    classify_app(error)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::sync::policy::{Budget, RetryPolicy};

    fn policy() -> SyncPolicy {
        SyncPolicy {
            budgets: super::super::policy::BudgetSet {
                build: Budget::new(Duration::from_secs(60)),
                connect: Budget::new(Duration::from_secs(5)),
                pull: Budget::new(Duration::from_secs(30)),
                push: Budget::new(Duration::from_secs(30)),
                stats: Budget::new(Duration::from_secs(5)),
                verify: Budget::new(Duration::from_secs(15)),
                shutdown: Budget::new(Duration::from_secs(15)),
            },
            retry: RetryPolicy {
                base: Duration::from_secs(5),
                factor: 2,
                max: Duration::from_secs(60),
                jitter_pct: 20,
                permanent_probe: Duration::from_secs(300),
            },
            freshness: FreshnessPolicy {
                content_max_age: Duration::from_secs(900),
                auth_max_age: Duration::from_secs(300),
                heartbeat_max_age: Duration::from_secs(180),
            },
            write_admission: super::super::policy::WriteAdmissionPolicy {
                max_pending_operations: 16,
                max_pending_bytes: 1024,
            },
        }
    }

    fn error(class: ErrorClass) -> SyncError {
        SyncError::new(class, "test failure")
    }

    fn healthy(at: Timestamp) -> SyncHealth {
        SyncHealth {
            last_success_pull_unix: at,
            heartbeat_unix: at,
            ..SyncHealth::default()
        }
    }

    fn apply(state: SyncState, health: &SyncHealth, event: SyncEvent) -> Transition {
        transition(state, health, &event, &policy(), 0.0).expect("valid transition")
    }

    #[test]
    fn a_successful_pull_never_crosses_the_verification_line() {
        let at = 100;
        let pulled = apply(
            SyncState::Verifying,
            &healthy(at),
            SyncEvent::PullSucceeded { changes: true, at },
        );
        assert_eq!(pulled.state, SyncState::Verifying);
        assert!(!pulled.readiness.http_ready());
    }

    #[test]
    fn verification_is_the_only_path_to_ready() {
        let at = 100;
        let verified = apply(
            SyncState::Verifying,
            &healthy(at),
            SyncEvent::ContractVerified { at },
        );
        assert_eq!(verified.state, SyncState::Ready);
        assert!(verified.readiness.http_ready());
    }

    #[test]
    fn a_transient_pull_failure_degrades_but_keeps_serving() {
        let at = 100;
        let failed = apply(
            SyncState::Ready,
            &healthy(at),
            SyncEvent::PullFailed {
                error: error(ErrorClass::TransientNetwork),
                at: at + 1,
            },
        );
        assert_eq!(
            failed.state,
            SyncState::Degraded(DegradedReason::Failure(ErrorClass::TransientNetwork))
        );
        assert!(failed.readiness.http_ready());
        assert!(failed.retry.is_some());
    }

    #[test]
    fn a_permanent_pull_failure_blocks_and_uses_the_slow_probe() {
        let at = 100;
        let failed = apply(
            SyncState::Ready,
            &healthy(at),
            SyncEvent::PullFailed {
                error: error(ErrorClass::Auth),
                at: at + 1,
            },
        );
        assert_eq!(failed.state, SyncState::Blocked(BlockedReason::Auth));
        assert!(!failed.readiness.http_ready());
        assert_eq!(failed.retry.expect("retry").delay, Duration::from_secs(300));
    }

    #[test]
    fn a_successful_pull_resets_consecutive_failures() {
        let at = 100;
        let mut health = healthy(at);
        health.consecutive_failures = 7;
        health.last_error_class = Some(ErrorClass::Timeout);
        let pulled = apply(
            SyncState::Degraded(DegradedReason::Failure(ErrorClass::Timeout)),
            &health,
            SyncEvent::PullSucceeded {
                changes: false,
                at: at + 1,
            },
        );
        assert_eq!(pulled.health.consecutive_failures, 0);
        assert_eq!(pulled.health.last_error_class, None);
        assert_eq!(pulled.state, SyncState::Ready);
    }

    #[test]
    fn a_contract_mismatch_is_a_blocked_schema_state() {
        let at = 100;
        let failed = apply(
            SyncState::Verifying,
            &healthy(at),
            SyncEvent::ContractMismatch {
                reason: "missing column".into(),
                at,
            },
        );
        assert_eq!(
            failed.state,
            SyncState::Blocked(BlockedReason::SchemaMismatch)
        );
        assert!(!failed.readiness.http_ready());
    }

    #[test]
    fn push_failures_do_not_change_read_trust() {
        let at = 100;
        let failed = apply(
            SyncState::Ready,
            &healthy(at),
            SyncEvent::PushFailed {
                error: error(ErrorClass::Auth),
                at: at + 1,
            },
        );
        assert_eq!(failed.state, SyncState::Ready);
        assert!(failed.readiness.http_ready());
        assert_eq!(failed.health.consecutive_push_failures, 1);
    }

    #[test]
    fn push_success_clears_pending_work_and_failure_marks_it_pending() {
        let status = SyncStatus::verified(policy());
        status.mark_write_committed(2, 512);
        let health = status.health();
        assert_eq!(health.pending_operations, 2);
        assert_eq!(health.pending_bytes, 512);
        assert!(health.push_pending);

        status.apply(SyncEvent::PushSucceeded { at: unix_now() });
        let health = status.health();
        assert_eq!(health.pending_operations, 0);
        assert_eq!(health.pending_bytes, 0);
        assert!(!health.push_pending);

        status.apply(SyncEvent::PushFailed {
            error: error(ErrorClass::TransientNetwork),
            at: unix_now(),
        });
        let health = status.health();
        assert!(health.push_pending);
        assert_eq!(health.pending_operations, 1);
        assert_eq!(health.consecutive_push_failures, 1);
    }

    #[test]
    fn stopping_latches_and_blocks_a_late_replica_error() {
        let status = SyncStatus::verified(policy());
        status.begin_stop();
        assert!(status.stop_requested());
        assert_eq!(status.state(), SyncState::Stopping);

        status.mark_blocked(BlockedReason::Auth);
        assert_eq!(status.state(), SyncState::Stopping);
    }

    #[test]
    fn readiness_separates_content_and_credential_freshness() {
        let at = 1_000;
        let mut health = healthy(at);
        health.last_success_pull_unix = at - 400;
        health.heartbeat_unix = at;
        let r = readiness(SyncState::Ready, &health, at, &policy().freshness);
        assert!(r.http_ready(), "15 minute content budget still holds");
        assert!(!r.allows_keyed_reads(), "5 minute auth budget is spent");
        assert_eq!(r.reason_label(), "auth_stale");

        health.last_success_pull_unix = at - 1_000;
        let r = readiness(SyncState::Ready, &health, at, &policy().freshness);
        assert!(!r.http_ready(), "content budget is also spent");
        assert!(!r.allows_public_reads());
    }

    #[test]
    fn a_stalled_supervisor_blocks_readiness_even_with_a_fresh_replica() {
        let at = 1_000;
        let mut health = healthy(at);
        health.heartbeat_unix = at - 181;
        let r = readiness(SyncState::Ready, &health, at, &policy().freshness);
        assert_eq!(r, Readiness::Blocked(BlockedReason::SupervisorStalled));
    }

    #[test]
    fn every_unverified_state_is_not_ready() {
        let at = 1_000;
        let health = healthy(at);
        for state in [
            SyncState::Starting,
            SyncState::Bootstrapping,
            SyncState::Verifying,
        ] {
            let r = readiness(state, &health, at, &policy().freshness);
            assert!(!r.http_ready(), "{state:?} must not be ready");
        }
    }

    #[test]
    fn stopped_is_terminal() {
        let at = 100;
        let result = apply(
            SyncState::Stopped,
            &healthy(at),
            SyncEvent::ContractVerified { at },
        );
        assert_eq!(result.state, SyncState::Stopped);
        assert!(!result.changed);
    }

    #[test]
    fn stopping_refuses_a_late_verification() {
        let at = 100;
        let result = apply(
            SyncState::Stopping,
            &healthy(at),
            SyncEvent::ContractVerified { at },
        );
        assert_eq!(result.state, SyncState::Stopping);
        assert!(!result.readiness.http_ready());
    }

    #[test]
    fn status_applies_events_and_exposes_one_snapshot() {
        let status = SyncStatus::new(policy());
        let now = unix_now();
        assert_eq!(status.state(), SyncState::Starting);
        assert!(!status.readiness().http_ready());

        status.apply(SyncEvent::BuildSucceeded { at: now });
        assert_eq!(status.state(), SyncState::Verifying);
        assert!(!status.readiness().http_ready());

        status.apply(SyncEvent::PullSucceeded {
            changes: true,
            at: now,
        });
        assert_eq!(status.state(), SyncState::Verifying);
        assert!(!status.readiness().http_ready());

        status.apply(SyncEvent::ContractVerified { at: now });
        assert_eq!(status.state(), SyncState::Ready);
        assert!(status.readiness().http_ready());
        assert_eq!(status.health().last_success_pull_unix, now);
    }

    #[test]
    fn a_failed_wake_throttles_the_next_request_path_attempt() {
        let status = SyncStatus::verified(policy());
        let at = unix_now();
        let delay = status.record_wake_failure(&error(ErrorClass::TransientNetwork), at);
        assert!(delay >= Duration::from_secs(5));
        assert!(!status.wake_allowed());
        assert_eq!(
            status.state(),
            SyncState::Degraded(DegradedReason::Failure(ErrorClass::TransientNetwork))
        );

        status.record_wake_success(false, at + 10_000);
        assert!(status.wake_allowed());
        assert_eq!(status.state(), SyncState::Ready);
    }
}
