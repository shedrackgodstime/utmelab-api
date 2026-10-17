use axum::{
    extract::{ConnectInfo, State},
    http::HeaderMap,
    Json,
};
use serde::Deserialize;
use std::net::SocketAddr;

use crate::{
    auth::session::{self, AdminUser, SessionUser},
    core::models::ServiceStatus,
    error::AppError,
    state::DbState,
    store,
};

/// Admin-only. Load balancers get liveness from `/health`; this carries the
/// operational counters, so it sits behind the admin session like the rest
/// of `internal` instead of leaking replica state to anonymous callers.
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

#[derive(Deserialize)]
pub struct LoginBody {
    pub username: String,
    pub password: String,
}

pub async fn login(
    State(s): State<DbState>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Json(b): Json<LoginBody>,
) -> Result<impl axum::response::IntoResponse, AppError> {
    if !s
        .limiter
        .check_login(&session::client_ip(&headers, addr))
        .await
    {
        return Err(AppError::RateLimited);
    }
    let (token, role) = store::accounts::login(&s, &b.username, &b.password).await?;
    let cookie = session::session_cookie_value(&token, s.cookie_secure);
    Ok((
        [(axum::http::header::SET_COOKIE, cookie)],
        Json(serde_json::json!({"ok": true, "role": role})),
    ))
}

pub async fn logout(
    State(s): State<DbState>,
    headers: HeaderMap,
) -> Result<impl axum::response::IntoResponse, AppError> {
    if let Some(tok) = session::cookie_token(&headers) {
        let _ = store::accounts::logout_session(&s, &tok).await;
    }
    Ok((
        [(axum::http::header::SET_COOKIE, session::expired_cookie())],
        Json(serde_json::json!({"ok": true})),
    ))
}

pub async fn my_keys(
    State(s): State<DbState>,
    SessionUser(u): SessionUser,
) -> Result<Json<Vec<store::accounts::KeySummary>>, AppError> {
    Ok(Json(store::accounts::list_keys(&s, Some(&u)).await?))
}

pub async fn create_key(
    State(s): State<DbState>,
    SessionUser(u): SessionUser,
) -> Result<Json<serde_json::Value>, AppError> {
    let full = store::accounts::create_key(&s, &u).await?;
    Ok(Json(serde_json::json!({"key": full})))
}

pub async fn delete_key(
    State(s): State<DbState>,
    SessionUser(u): SessionUser,
    Json(b): Json<crate::core::models::PrefixBody>,
) -> Result<Json<serde_json::Value>, AppError> {
    let deleted = store::accounts::delete_key(&s, &u, &b.prefix).await?;
    Ok(Json(serde_json::json!({"ok": deleted})))
}
