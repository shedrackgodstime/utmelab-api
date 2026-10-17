//! Admin-only operations. Same core/store calls the MCP admin tools
//! use — one operation, two surfaces, never duplicated. Every mutation
//! passes the acting admin to the store so the audit event is attributable.

use axum::{extract::State, Json};

use crate::{
    auth::session::AdminUser, core::models::ServiceStatus, error::AppError, state::DbState, store,
};

#[derive(serde::Deserialize)]
pub struct RoleBody {
    pub username: String,
    pub role: String,
}

/// Admin-only. Load balancers get liveness from `/health`; this carries the
/// operational counters and request telemetry, so it sits on the admin
/// surface instead of leaking replica state to anonymous callers.
pub async fn status(State(s): State<DbState>, AdminUser(_): AdminUser) -> Json<ServiceStatus> {
    let m = s.metrics.snapshot();
    Json(ServiceStatus {
        service: "utmelab-api",
        has_sync: s.db.read().await.is_some(),
        contract_ok: s.contract_ok.load(std::sync::atomic::Ordering::Relaxed),
        gate_rejections: m.gate_rejections,
        pulls_applied: m.pulls_applied,
        pulls_empty: m.pulls_empty,
        last_pull_unix: m.last_pull_unix,
        requests_ok: m.requests_ok,
        requests_client_error: m.requests_client_error,
        requests_server_error: m.requests_server_error,
        in_flight: m.in_flight,
        latency_fast: m.latency_fast,
        latency_ok: m.latency_ok,
        latency_slow: m.latency_slow,
    })
}

pub async fn list_users(
    State(s): State<DbState>,
    AdminUser(_u): AdminUser,
) -> Result<Json<Vec<store::accounts::UserSummary>>, AppError> {
    Ok(Json(store::accounts::list_users(&s).await?))
}

pub async fn set_role(
    State(s): State<DbState>,
    AdminUser(u): AdminUser,
    Json(b): Json<RoleBody>,
) -> Result<Json<serde_json::Value>, AppError> {
    let found = store::accounts::set_user_role(&s, &b.username, &b.role, &u).await?;
    Ok(Json(serde_json::json!({"ok": found})))
}

pub async fn create_admin_key(
    State(s): State<DbState>,
    AdminUser(u): AdminUser,
) -> Result<Json<serde_json::Value>, AppError> {
    let full = store::accounts::create_admin_key(&s, &u).await?;
    Ok(Json(serde_json::json!({"key": full})))
}

pub async fn list_keys(
    State(s): State<DbState>,
    AdminUser(_u): AdminUser,
) -> Result<Json<Vec<store::accounts::KeySummary>>, AppError> {
    Ok(Json(store::accounts::list_keys(&s, None).await?))
}

pub async fn revoke(
    State(s): State<DbState>,
    AdminUser(u): AdminUser,
    Json(b): Json<crate::core::models::PrefixBody>,
) -> Result<Json<serde_json::Value>, AppError> {
    let found = store::accounts::set_revoked(&s, &b.prefix, true, &u).await?;
    Ok(Json(serde_json::json!({"ok": found})))
}

pub async fn unrevoke(
    State(s): State<DbState>,
    AdminUser(u): AdminUser,
    Json(b): Json<crate::core::models::PrefixBody>,
) -> Result<Json<serde_json::Value>, AppError> {
    let found = store::accounts::set_revoked(&s, &b.prefix, false, &u).await?;
    Ok(Json(serde_json::json!({"ok": found})))
}
