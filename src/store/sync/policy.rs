//! The one place sync timing, retry, freshness, and write admission are
//! decided.
//!
//! Nothing in the sync loops may invent a delay, a timeout, or a readiness
//! rule. Values come from [`SyncPolicy`], decisions come from the pure
//! functions here, and the only side effect is the random jitter sample the
//! caller supplies. That keeps every policy testable without a clock or a
//! network.

use std::time::Duration;

use crate::{config::Config, error::AppError};

/// A push notification is the fast path. This fallback only recovers pending
/// local work after a restart or a missed notification.
pub const PUSH_FALLBACK: Duration = Duration::from_secs(300);
/// Small debounce window that lets a burst of local writes share one push.
pub const PUSH_COALESCE: Duration = Duration::from_millis(25);
/// Expired dashboard sessions are purged on this cadence, not on the request
/// path.
pub const PURGE_EVERY: Duration = Duration::from_secs(3600);
/// How often a sleeping replica rechecks whether traffic has returned.
pub const SLEEP_RECHECK: Duration = Duration::from_secs(60);

/// Wall-clock seconds since the Unix epoch. Zero means "not recorded"; no
/// real event is stamped at zero.
pub type Timestamp = u64;

/// A mandatory operation budget. The newtype exists so an engine call cannot
/// be written without naming which budget it spends.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Budget(Duration);

impl Budget {
    pub const fn new(duration: Duration) -> Self {
        Self(duration)
    }

    pub const fn duration(self) -> Duration {
        self.0
    }
}

/// Every budget an engine operation can spend.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BudgetSet {
    pub build: Budget,
    pub connect: Budget,
    pub pull: Budget,
    pub push: Budget,
    pub stats: Budget,
    pub verify: Budget,
    pub shutdown: Budget,
}

/// How a failure should be retried. Classification happens once, beside the
/// typed error, so no loop guesses from prose in two different places.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum ErrorClass {
    /// Connect refused, reset, DNS failure, TLS handshake failure.
    TransientNetwork,
    /// Remote 429 or 5xx, sync busy at the service boundary.
    TransientRemote,
    /// The operation exceeded its budget.
    Timeout,
    /// Missing, invalid, or revoked credentials.
    Auth,
    /// Bad URL, unsupported scheme, invalid token shape, invalid path.
    Configuration,
    /// Disk full, permission denied, corrupt or not-a-database local file.
    LocalStorage,
    /// The replica shape is not the one this build reads.
    Schema,
    /// Engine busy or snapshot busy. Clears on its own.
    Contention,
    /// A type or conversion failure the loop cannot reason about.
    Unknown,
}

impl ErrorClass {
    /// Permanent classes do not heal by retrying the same call quickly. They
    /// get the slow probe and they block readiness until an operator acts.
    pub const fn is_permanent(self) -> bool {
        matches!(
            self,
            Self::Auth | Self::Configuration | Self::LocalStorage | Self::Schema
        )
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::TransientNetwork => "transient_network",
            Self::TransientRemote => "transient_remote",
            Self::Timeout => "timeout",
            Self::Auth => "auth",
            Self::Configuration => "configuration",
            Self::LocalStorage => "local_storage",
            Self::Schema => "schema",
            Self::Contention => "contention",
            Self::Unknown => "unknown",
        }
    }
}

/// A classified sync failure. The message is for operators, never for clients.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SyncError {
    pub class: ErrorClass,
    pub message: String,
}

impl SyncError {
    pub fn new(class: ErrorClass, message: impl Into<String>) -> Self {
        Self {
            class,
            message: message.into(),
        }
    }

    pub fn timeout(operation: &str, budget: Budget) -> Self {
        Self::new(
            ErrorClass::Timeout,
            format!(
                "{operation} exceeded its {}s budget",
                budget.duration().as_secs()
            ),
        )
    }
}

impl std::fmt::Display for SyncError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.class.as_str(), self.message)
    }
}

impl std::error::Error for SyncError {}

/// Classify a typed engine error. This is the only place error text is
/// consulted, and it is consulted beside the typed variants, on engine errors
/// only. Everything else keeps its variant.
pub fn classify_engine(error: &turso::Error) -> ErrorClass {
    use turso::Error as E;
    match error {
        E::Busy(_) | E::BusySnapshot(_) => ErrorClass::Contention,
        E::Interrupt(_) => ErrorClass::Timeout,
        E::Readonly(_) | E::DatabaseFull(_) | E::NotAdb(_) | E::Corrupt(_) | E::IoError(..) => {
            ErrorClass::LocalStorage
        }
        E::ToSqlConversionFailure(_) | E::ConversionFailure(_) | E::Constraint(_) => {
            ErrorClass::Unknown
        }
        E::QueryReturnedNoRows => ErrorClass::Unknown,
        E::BatchStatementFailed { error, .. } | E::BatchRollbackFailed { error, .. } => {
            classify_engine(error)
        }
        E::Misuse(_) => ErrorClass::Unknown,
        E::Error(message) => classify_message(message),
    }
}

/// Classify an [`AppError`]. Contention and schema are already typed; the
/// rest are mapped from the boundary that produced them.
pub fn classify_app(error: &AppError) -> ErrorClass {
    match error {
        AppError::DbContended | AppError::DbSaturated => ErrorClass::Contention,
        AppError::DbUnavailable(_) => ErrorClass::Configuration,
        AppError::SchemaMismatch => ErrorClass::Schema,
        AppError::RequestTimeout => ErrorClass::Timeout,
        AppError::Unauthorized | AppError::Forbidden => ErrorClass::Auth,
        AppError::Upstream(message) | AppError::Internal(message) => classify_message(message),
        AppError::BadRequest(_)
        | AppError::NotFound
        | AppError::Conflict(_)
        | AppError::RateLimited => ErrorClass::Unknown,
    }
}

/// Text inspection at the transport boundary. Keep this narrow: a token, a
/// URL problem, a timeout, and a remote status are the only cases the engine
/// cannot express as a typed variant.
fn classify_message(message: &str) -> ErrorClass {
    let m = message.to_ascii_lowercase();
    if m.contains("401")
        || m.contains("403")
        || m.contains("unauthorized")
        || m.contains("forbidden")
        || m.contains("invalid token")
        || m.contains("token expired")
    {
        return ErrorClass::Auth;
    }
    if m.contains("invalid url")
        || m.contains("invalid scheme")
        || m.contains("unsupported scheme")
        || m.contains("invalid replica")
        || m.contains("not a database")
    {
        return ErrorClass::Configuration;
    }
    if m.contains("no such table")
        || m.contains("no such column")
        || m.contains("schema")
        || m.contains("migration")
    {
        return ErrorClass::Schema;
    }
    if m.contains("429") || m.contains("rate limit") || m.contains("too many requests") {
        return ErrorClass::TransientRemote;
    }
    if m.contains("500")
        || m.contains("502")
        || m.contains("503")
        || m.contains("504")
        || m.contains("server error")
        || m.contains("service unavailable")
    {
        return ErrorClass::TransientRemote;
    }
    if m.contains("timed out") || m.contains("timeout") || m.contains("deadline") {
        return ErrorClass::Timeout;
    }
    if m.contains("connection refused")
        || m.contains("connection reset")
        || m.contains("connection closed")
        || m.contains("dns")
        || m.contains("tls")
        || m.contains("certificate")
        || m.contains("unreachable")
        || m.contains("network")
    {
        return ErrorClass::TransientNetwork;
    }
    if m.contains("no space") || m.contains("permission denied") || m.contains("read-only") {
        return ErrorClass::LocalStorage;
    }
    ErrorClass::Unknown
}

/// Exponential backoff with additive jitter. Jitter never lowers a delay below
/// the base, so a busy remote is never hit earlier than policy allows.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RetryPolicy {
    pub base: Duration,
    pub factor: u32,
    pub max: Duration,
    pub jitter_pct: u8,
    pub permanent_probe: Duration,
}

impl RetryPolicy {
    /// `attempt` is one-based. `jitter_sample` is in `[0, 1)`, supplied by the
    /// caller so the decision stays pure.
    pub fn delay(&self, attempt: u32, class: ErrorClass, jitter_sample: f64) -> Duration {
        if class.is_permanent() {
            return self.permanent_probe;
        }
        let exponent = attempt.saturating_sub(1);
        let factor = self.factor.max(1);
        let scaled = self
            .base
            .checked_mul(factor.saturating_pow(exponent))
            .unwrap_or(self.max);
        let capped = scaled.min(self.max);
        let sample = if jitter_sample.is_finite() {
            jitter_sample.clamp(0.0, 1.0)
        } else {
            0.0
        };
        let extra = capped.mul_f64((self.jitter_pct as f64 / 100.0) * sample);
        (capped + extra).min(self.max)
    }
}

/// How old the last successful pull may be while a surface still trusts the
/// replica. Content and credentials are deliberately separate budgets.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FreshnessPolicy {
    pub content_max_age: Duration,
    pub auth_max_age: Duration,
    pub heartbeat_max_age: Duration,
}

/// What to do when a write arrives while pushes are already behind. The
/// policy is explicit so an outage cannot choose "unbounded" by accident.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct WriteAdmissionPolicy {
    pub max_pending_operations: u64,
    pub max_pending_bytes: u64,
}

/// What is known about unsent local work.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PendingWork {
    Known { operations: u64, bytes: u64 },
    Unknown,
}

/// One write admission decision.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WriteDecision {
    Admit,
    Reject(WriteRejection),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WriteRejection {
    PendingOperationBudget,
    PendingByteBudget,
}

/// The complete sync policy. Construct once at boot; never mutate in place.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SyncPolicy {
    pub budgets: BudgetSet,
    pub retry: RetryPolicy,
    pub freshness: FreshnessPolicy,
    pub write_admission: WriteAdmissionPolicy,
}

impl SyncPolicy {
    pub fn from_config(cfg: &Config) -> Self {
        let secs = Duration::from_secs;
        Self {
            budgets: BudgetSet {
                build: Budget::new(secs(cfg.sync_build_timeout_secs)),
                connect: Budget::new(secs(cfg.sync_connect_timeout_secs)),
                pull: Budget::new(secs(cfg.sync_pull_timeout_secs)),
                push: Budget::new(secs(cfg.sync_push_timeout_secs)),
                stats: Budget::new(secs(cfg.sync_stats_timeout_secs)),
                verify: Budget::new(secs(cfg.sync_verify_timeout_secs)),
                shutdown: Budget::new(secs(cfg.sync_shutdown_timeout_secs)),
            },
            retry: RetryPolicy {
                base: secs(cfg.sync_retry_base_secs),
                factor: cfg.sync_retry_factor,
                max: secs(cfg.sync_retry_max_secs),
                jitter_pct: cfg.sync_retry_jitter_pct,
                permanent_probe: secs(cfg.sync_permanent_probe_secs),
            },
            freshness: FreshnessPolicy {
                content_max_age: secs(cfg.sync_max_staleness_secs),
                auth_max_age: secs(cfg.sync_auth_max_staleness_secs),
                heartbeat_max_age: secs(cfg.sync_heartbeat_max_secs),
            },
            write_admission: WriteAdmissionPolicy {
                max_pending_operations: cfg.sync_max_pending_operations,
                max_pending_bytes: cfg.sync_max_pending_bytes,
            },
        }
    }

    pub fn retry_delay(&self, attempt: u32, class: ErrorClass, jitter_sample: f64) -> Duration {
        self.retry.delay(attempt, class, jitter_sample)
    }
}

impl Default for SyncPolicy {
    fn default() -> Self {
        Self::from_config(&Config::default())
    }
}

/// Admission is a pure decision: the caller reads pending work, this decides.
pub fn admit_write(pending: PendingWork, policy: &WriteAdmissionPolicy) -> WriteDecision {
    match pending {
        PendingWork::Unknown => WriteDecision::Admit,
        PendingWork::Known { operations, bytes } => {
            if operations >= policy.max_pending_operations {
                WriteDecision::Reject(WriteRejection::PendingOperationBudget)
            } else if bytes >= policy.max_pending_bytes {
                WriteDecision::Reject(WriteRejection::PendingByteBudget)
            } else {
                WriteDecision::Admit
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn policy() -> RetryPolicy {
        RetryPolicy {
            base: Duration::from_secs(5),
            factor: 2,
            max: Duration::from_secs(60),
            jitter_pct: 20,
            permanent_probe: Duration::from_secs(300),
        }
    }

    #[test]
    fn retry_grows_to_the_cap_and_never_exceeds_it() {
        let p = policy();
        let first = p.delay(1, ErrorClass::TransientNetwork, 0.0);
        let second = p.delay(2, ErrorClass::TransientNetwork, 0.0);
        let third = p.delay(3, ErrorClass::TransientNetwork, 0.0);
        assert_eq!(first, Duration::from_secs(5));
        assert_eq!(second, Duration::from_secs(10));
        assert_eq!(third, Duration::from_secs(20));

        for attempt in 1..20 {
            let delay = p.delay(attempt, ErrorClass::TransientNetwork, 1.0);
            assert!(delay <= p.max, "attempt {attempt}: {delay:?}");
        }
    }

    #[test]
    fn jitter_only_adds_and_stays_inside_the_configured_band() {
        let p = policy();
        let no_jitter = p.delay(3, ErrorClass::TransientRemote, 0.0);
        let full_jitter = p.delay(3, ErrorClass::TransientRemote, 1.0);
        let mid = p.delay(3, ErrorClass::TransientRemote, 0.5);
        assert_eq!(no_jitter, Duration::from_secs(20));
        assert_eq!(full_jitter, Duration::from_secs(24));
        assert_eq!(mid, Duration::from_secs(22));
        assert!(full_jitter <= p.max);
    }

    #[test]
    fn permanent_classes_use_the_slow_probe_not_the_fast_path() {
        let p = policy();
        for class in [
            ErrorClass::Auth,
            ErrorClass::Configuration,
            ErrorClass::LocalStorage,
            ErrorClass::Schema,
        ] {
            assert_eq!(p.delay(1, class, 0.0), Duration::from_secs(300));
            assert_eq!(p.delay(20, class, 1.0), Duration::from_secs(300));
            assert!(class.is_permanent());
        }
        assert!(!ErrorClass::Timeout.is_permanent());
        assert!(!ErrorClass::Contention.is_permanent());
    }

    #[test]
    fn typed_engine_errors_keep_their_class() {
        assert_eq!(
            classify_engine(&turso::Error::Busy("busy".into())),
            ErrorClass::Contention
        );
        assert_eq!(
            classify_engine(&turso::Error::DatabaseFull("full".into())),
            ErrorClass::LocalStorage
        );
        assert_eq!(
            classify_engine(&turso::Error::Corrupt("bad".into())),
            ErrorClass::LocalStorage
        );
        assert_eq!(
            classify_engine(&turso::Error::Error("HTTP 401 unauthorized".into())),
            ErrorClass::Auth
        );
        assert_eq!(
            classify_engine(&turso::Error::Error("no such table: exams".into())),
            ErrorClass::Schema
        );
        assert_eq!(
            classify_engine(&turso::Error::Error("HTTP 429 rate limit".into())),
            ErrorClass::TransientRemote
        );
    }

    #[test]
    fn app_errors_are_classified_at_the_boundary() {
        assert_eq!(classify_app(&AppError::DbContended), ErrorClass::Contention);
        assert_eq!(classify_app(&AppError::SchemaMismatch), ErrorClass::Schema);
        assert_eq!(classify_app(&AppError::Unauthorized), ErrorClass::Auth);
        assert_eq!(classify_app(&AppError::RequestTimeout), ErrorClass::Timeout);
        assert_eq!(
            classify_app(&AppError::Upstream("connection refused".into())),
            ErrorClass::TransientNetwork
        );
    }

    #[test]
    fn timeout_carries_the_operation_and_budget() {
        let e = SyncError::timeout("pull", Budget::new(Duration::from_secs(30)));
        assert_eq!(e.class, ErrorClass::Timeout);
        assert!(e.message.contains("pull"));
        assert!(e.message.contains("30"));
    }

    #[test]
    fn every_config_value_reaches_the_policy() {
        let cfg = Config::default();
        let p = SyncPolicy::from_config(&cfg);
        assert_eq!(
            p.budgets.pull.duration(),
            Duration::from_secs(cfg.sync_pull_timeout_secs)
        );
        assert_eq!(p.retry.base, Duration::from_secs(cfg.sync_retry_base_secs));
        assert_eq!(
            p.freshness.auth_max_age,
            Duration::from_secs(cfg.sync_auth_max_staleness_secs)
        );
        assert_eq!(
            p.freshness.heartbeat_max_age,
            Duration::from_secs(cfg.sync_heartbeat_max_secs)
        );
        assert_eq!(
            p.write_admission.max_pending_operations,
            cfg.sync_max_pending_operations
        );
        assert_eq!(
            p.write_admission.max_pending_bytes,
            cfg.sync_max_pending_bytes
        );
    }

    #[test]
    fn write_admission_is_a_decision_not_a_default() {
        let policy = WriteAdmissionPolicy {
            max_pending_operations: 10,
            max_pending_bytes: 1000,
        };
        assert_eq!(
            admit_write(
                PendingWork::Known {
                    operations: 9,
                    bytes: 999
                },
                &policy
            ),
            WriteDecision::Admit
        );
        assert_eq!(
            admit_write(
                PendingWork::Known {
                    operations: 10,
                    bytes: 0
                },
                &policy
            ),
            WriteDecision::Reject(WriteRejection::PendingOperationBudget)
        );
        assert_eq!(
            admit_write(
                PendingWork::Known {
                    operations: 0,
                    bytes: 1000
                },
                &policy
            ),
            WriteDecision::Reject(WriteRejection::PendingByteBudget)
        );
        assert_eq!(
            admit_write(PendingWork::Unknown, &policy),
            WriteDecision::Admit
        );
    }
}
