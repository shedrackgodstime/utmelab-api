//! Two probes with two jobs. `/health` is liveness: the process is up, which
//! is true the moment it can answer at all. `/ready` is readiness: the
//! replica is open and its schema contract is trusted, so the data surfaces
//! will actually serve. A proxy or orchestrator routes on `/ready` and only
//! restarts on `/health`.

use axum::extract::State;

use crate::{
    error::AppError,
    state::{DbState, HealthState},
    store::sync::{BlockedReason, Readiness},
};

// Takes the narrow substate (not the full AppState) so the wiring stays
// honest even though this handler needs nothing from it.
pub async fn health(_s: State<HealthState>) -> &'static str {
    "ok"
}

/// Readiness. 503 until the first pull, local schema work, and contract check
/// have completed and the replica is inside the freshness budget. Deliberately
/// not behind the contract guard: this is the signal that tells a caller the
/// guard is up.
pub async fn ready(State(s): State<DbState>) -> Result<&'static str, AppError> {
    if s.db.read().await.is_none() {
        return Err(AppError::DbUnavailable("sync"));
    }
    let readiness = s.sync.readiness();
    if readiness.http_ready() {
        return Ok("ok");
    }
    Err(match readiness {
        Readiness::Blocked(BlockedReason::SchemaMismatch) => AppError::SchemaMismatch,
        _ => AppError::DbUnavailable("sync"),
    })
}
