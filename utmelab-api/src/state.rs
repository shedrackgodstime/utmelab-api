//! Process-wide shared state and narrow per-handler views.
//!
//! Handlers take `HealthState` or `DbState` via `FromRef` so hot paths never
//! see handles they do not need (`HealthState` carries no database at all).

use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};

use tokio::sync::RwLock;

use crate::store::{DbGate, SyncDb};

use super::auth::rate_limit::RateLimiter;

/// Lock-free counters. Read by ops/status surfaces; never on a hot path.
#[derive(Default)]
pub struct Metrics {
    pub gate_rejections: AtomicU64,
    pub pulls_applied: AtomicU64,
    pub pulls_empty: AtomicU64,
}

impl Metrics {
    pub fn snapshot(&self) -> MetricsSnapshot {
        MetricsSnapshot {
            gate_rejections: self.gate_rejections.load(Ordering::Relaxed),
            pulls_applied: self.pulls_applied.load(Ordering::Relaxed),
            pulls_empty: self.pulls_empty.load(Ordering::Relaxed),
        }
    }
}

pub struct MetricsSnapshot {
    pub gate_rejections: u64,
    pub pulls_applied: u64,
    pub pulls_empty: u64,
}

pub type SharedMetrics = Arc<Metrics>;

pub type SharedLimiter = Arc<RateLimiter>;

#[derive(Clone)]
pub struct AppState {
    pub name: Arc<str>,
    pub db: SyncCell,
    pub db_gate: DbGate,
    pub metrics: SharedMetrics,
    pub cookie_secure: bool,
    pub write_mutex: WriteMutex,
    pub contract_ok: ContractFlag,
    pub limiter: SharedLimiter,
}

pub type SyncCell = Arc<RwLock<Option<SyncDb>>>;
pub type WriteMutex = Arc<tokio::sync::Mutex<()>>;
// Contract health. Set by the sync task; read by status without a permit.
pub type ContractFlag = Arc<std::sync::atomic::AtomicBool>;

#[derive(Clone)]
pub struct HealthState {
    pub name: Arc<str>,
}

impl axum::extract::FromRef<AppState> for HealthState {
    fn from_ref(state: &AppState) -> Self {
        Self {
            name: Arc::clone(&state.name),
        }
    }
}

#[derive(Clone)]
pub struct DbState {
    pub db: SyncCell,
    pub db_gate: DbGate,
    pub metrics: SharedMetrics,
    pub cookie_secure: bool,
    pub write_mutex: WriteMutex,
    pub contract_ok: ContractFlag,
    pub limiter: SharedLimiter,
}

impl DbState {
    /// One-shot commands (`seed-admin`): fresh gate, no sharing.
    pub fn detached(db: SyncDb) -> Self {
        Self {
            db: Arc::new(RwLock::new(Some(db))),
            db_gate: Arc::new(tokio::sync::Semaphore::new(
                crate::config::DEFAULT_DB_MAX_CONCURRENT,
            )),
            metrics: Arc::new(Metrics::default()),
            cookie_secure: false,
            write_mutex: Arc::new(tokio::sync::Mutex::new(())),
            contract_ok: Arc::new(std::sync::atomic::AtomicBool::new(true)),
            limiter: Arc::new(crate::auth::rate_limit::RateLimiter::new()),
        }
    }
}

impl axum::extract::FromRef<AppState> for DbState {
    fn from_ref(state: &AppState) -> Self {
        Self {
            db: Arc::clone(&state.db),
            db_gate: Arc::clone(&state.db_gate),
            metrics: Arc::clone(&state.metrics),
            cookie_secure: state.cookie_secure,
            write_mutex: Arc::clone(&state.write_mutex),
            contract_ok: Arc::clone(&state.contract_ok),
            limiter: Arc::clone(&state.limiter),
        }
    }
}
