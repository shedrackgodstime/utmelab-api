//! Admin-only operations. Same core/store calls the MCP admin tools
//! use: one operation, two surfaces, never duplicated. Every mutation
//! passes the acting admin to the store so the audit event is attributable.

use axum::{extract::State, http::HeaderMap, Json};

use crate::{
    auth::session::AdminUser,
    core::models::{Applied, NewKey, NewKeySpec, PrefixBody, ServiceStatus},
    error::AppError,
    state::DbState,
    store,
};

#[derive(serde::Deserialize)]
pub struct RoleBody {
    pub username: String,
    pub role: String,
}

/// Admin-only. Load balancers get liveness from `/health`; this carries the
/// operational counters and request telemetry, so it sits on the admin
/// surface instead of leaking replica state to anonymous callers.
pub async fn status(
    State(s): State<DbState>,
    AdminUser(_): AdminUser,
) -> Result<Json<ServiceStatus>, AppError> {
    let m = s.metrics.snapshot();
    let health = s.sync.health();
    let now = store::sync::unix_now();
    let staleness_secs = if health.last_success_pull_unix == 0 {
        0
    } else {
        now.saturating_sub(health.last_success_pull_unix)
    };
    Ok(Json(ServiceStatus {
        service: "utmelab-api",
        has_sync: s.db.read().await.is_some(),
        contract_ok: s.sync.readiness().allows_public_reads(),
        sync_state: s.sync.state().label(),
        sync_readiness: s.sync.readiness().reason_label(),
        last_success_pull_unix: health.last_success_pull_unix,
        sync_staleness_secs: staleness_secs,
        sync_consecutive_failures: health.consecutive_failures as u64,
        sync_last_error: health.last_error_class.map(|c| c.as_str()),
        sync_pending_operations: health.pending_operations,
        sync_pending_bytes: health.pending_bytes,
        sync_push_pending: health.push_pending,
        sync_sleeping: health.sleeping,
        sync_last_attempt_pull_unix: health.last_attempt_pull_unix,
        sync_last_attempt_push_unix: health.last_attempt_push_unix,
        sync_last_success_push_unix: health.last_success_push_unix,
        sync_consecutive_push_failures: health.consecutive_push_failures as u64,
        sync_heartbeat_unix: health.heartbeat_unix,
        sync_last_error_unix: health.last_error_unix,
        sync: store::sync::stats(&s).await?,
        gate_rejections: m.gate_rejections,
        pulls_applied: m.pulls_applied,
        pulls_empty: m.pulls_empty,
        sync_failures: m.sync_failures,
        last_pull_unix: m.last_pull_unix,
        last_pull_duration_ms: m.last_pull_duration_ms,
        last_request_unix: m.last_request_unix,
        write_wait_count: m.write_wait_count,
        write_wait_ms_total: m.write_wait_ms_total,
        write_wait_ms_max: m.write_wait_ms_max,
        local_write_count: m.local_write_count,
        local_write_ms_total: m.local_write_ms_total,
        local_write_ms_max: m.local_write_ms_max,
        local_write_avg_ms: m.local_write_avg_ms,
        push_count: m.push_count,
        push_ms_total: m.push_ms_total,
        push_ms_max: m.push_ms_max,
        push_avg_ms: m.push_avg_ms,
        last_push_duration_ms: m.last_push_duration_ms,
        requests_ok: m.requests_ok,
        requests_client_error: m.requests_client_error,
        requests_server_error: m.requests_server_error,
        in_flight: m.in_flight,
        latency_fast: m.latency_fast,
        latency_ok: m.latency_ok,
        latency_slow: m.latency_slow,
    }))
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
) -> Result<Json<Applied>, AppError> {
    let found = store::accounts::set_user_role(&s, &b.username, &b.role, &u).await?;
    Ok(Json(Applied { ok: found }))
}

/// Admin-only. `tier` decides the grant, so this mints a consumer key or a
/// staff key and nothing in between; a consumer key also carries its `owner`.
pub async fn create_key(
    State(s): State<DbState>,
    AdminUser(u): AdminUser,
    headers: HeaderMap,
    Json(b): Json<NewKeySpec>,
) -> Result<Json<NewKey>, AppError> {
    let Some(value) = headers.get("idempotency-key") else {
        return Err(AppError::BadRequest("missing idempotency key".to_string()));
    };
    let idempotency_key = value
        .to_str()
        .map_err(|_| AppError::BadRequest("invalid idempotency key".to_string()))?
        .trim();
    if idempotency_key.is_empty() || idempotency_key.len() > 128 {
        return Err(AppError::BadRequest("invalid idempotency key".to_string()));
    }
    let key = store::accounts::create_key_spec_idempotent(
        &s,
        &u,
        &b.tier,
        &b.owner,
        Some(idempotency_key),
    )
    .await?;
    Ok(Json(NewKey { key }))
}

pub async fn rotate(
    State(s): State<DbState>,
    AdminUser(u): AdminUser,
    Json(b): Json<PrefixBody>,
) -> Result<Json<NewKey>, AppError> {
    let key = store::accounts::rotate_key(&s, &b.prefix, &u).await?;
    Ok(Json(NewKey { key }))
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
    Json(b): Json<PrefixBody>,
) -> Result<Json<Applied>, AppError> {
    apply(s, u, b.prefix, true).await
}

pub async fn unrevoke(
    State(s): State<DbState>,
    AdminUser(u): AdminUser,
    Json(b): Json<PrefixBody>,
) -> Result<Json<Applied>, AppError> {
    apply(s, u, b.prefix, false).await
}

/// Admin-only: list filed consumer reports, newest first. Capped at 200;
/// older reports are no longer visible through this surface.
pub async fn list_reports(
    State(s): State<DbState>,
    AdminUser(_u): AdminUser,
) -> Result<Json<Vec<crate::core::models::ReportSummary>>, AppError> {
    Ok(Json(store::accounts::list_reports(&s).await?))
}

/// The body both revoke routes share; they differ only by the flag.
async fn apply(
    s: DbState,
    actor: String,
    prefix: String,
    revoked: bool,
) -> Result<Json<Applied>, AppError> {
    let ok = store::accounts::set_revoked(&s, &prefix, revoked, &actor).await?;
    Ok(Json(Applied { ok }))
}

#[cfg(test)]
mod tests {
    use crate::testing::{
        api_schema, call_session, call_session_with_headers, connect, issue_session, replica, state,
    };
    use axum::http::StatusCode;

    const CREATE: &str = "/api/internal/admin/keys/create";

    /// A replica with the account tables and two signed-in dashboard users:
    /// `ada` is an admin, `sam` a customer. The returned tokens are the raw
    /// cookie values; the table keeps only their hashes.
    async fn app() -> (axum::Router, crate::store::SyncDb, String, String) {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        let now = crate::auth::session::now_unix();
        for (user, role, token) in [
            ("ada", "admin", "ada-token"),
            ("sam", "customer", "sam-token"),
        ] {
            issue_session(&conn, user, role, token, now + 3600).await;
        }
        let app = crate::routes::router(state(db.clone()), &crate::config::Config::default());
        (app, db, "ada-token".to_string(), "sam-token".to_string())
    }

    /// An admin session mints a consumer key with the owner it named. The
    /// replica is offline, so the write commits locally and the background
    /// push remains pending; the committed row is what this test reads.
    #[tokio::test]
    async fn an_admin_session_mints_a_consumer_key_for_an_owner() {
        let (app, db, admin, customer) = app().await;

        let (status, body) = call_session_with_headers(
            app.clone(),
            "POST",
            CREATE,
            &admin,
            &[("idempotency-key", "admin-test-1")],
            Some(r#"{"tier":"commercial","owner":"utmelab-app"}"#),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{body}");

        let conn = connect(&db).await;
        let mut rows = conn
            .query("SELECT tier, scopes, owner FROM api_keys", ())
            .await
            .expect("query");
        let row = rows.next().await.expect("next").expect("row");
        assert_eq!(row.get::<String>(0).expect("tier"), "commercial");
        assert_eq!(
            row.get::<String>(1).expect("scopes"),
            "read:catalog,write:reports"
        );
        assert_eq!(row.get::<String>(2).expect("owner"), "utmelab-app");

        // A customer session is refused at the door, before the body is read.
        let (status, _) = call_session(
            app,
            "POST",
            CREATE,
            &customer,
            Some(r#"{"tier":"commercial","owner":"utmelab-app"}"#),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
    }

    /// The tier decides the grant, so a caller cannot name a scope or a tier
    /// the store does not know: the request is refused before any write.
    #[tokio::test]
    async fn an_admin_session_cannot_mint_a_half_granted_key() {
        let (app, _db, admin, _customer) = app().await;
        let (status, body) = call_session(
            app,
            "POST",
            CREATE,
            &admin,
            Some(r#"{"tier":"root","owner":"utmelab-app"}"#),
        )
        .await;
        assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");
        assert_eq!(body["code"], "bad_request", "{body}");
    }
}
