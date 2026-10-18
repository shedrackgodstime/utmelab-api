//! Admin-only operations. Same core/store calls the MCP admin tools
//! use — one operation, two surfaces, never duplicated. Every mutation
//! passes the acting admin to the store so the audit event is attributable.

use axum::{extract::State, Json};

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
    Ok(Json(ServiceStatus {
        service: "utmelab-api",
        has_sync: s.db.read().await.is_some(),
        contract_ok: s.contract_ok.load(std::sync::atomic::Ordering::Relaxed),
        sync: store::sync::stats(&s).await?,
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
    Json(b): Json<NewKeySpec>,
) -> Result<Json<NewKey>, AppError> {
    let key = store::accounts::create_key_spec(&s, &u, &b.tier, &b.owner).await?;
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
    use crate::testing::{api_schema, call_session, connect, replica, state};
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
            conn.execute(
                "INSERT INTO dashboard_users (username, pw_hash, role) VALUES (?1, 'unused', ?2)",
                vec![
                    turso::Value::Text(user.to_string()),
                    turso::Value::Text(role.to_string()),
                ],
            )
            .await
            .expect("seed user");
            conn.execute(
                "INSERT INTO sessions (token_hash, username, expires_at) VALUES (?1, ?2, ?3)",
                vec![
                    turso::Value::Text(crate::store::accounts::hash_key(token)),
                    turso::Value::Text(user.to_string()),
                    turso::Value::Integer(now + 3600),
                ],
            )
            .await
            .expect("seed session");
        }
        let app = crate::routes::router(state(db.clone()), &crate::config::Config::default());
        (app, db, "ada-token".to_string(), "sam-token".to_string())
    }

    /// An admin session mints a consumer key with the owner it named. The
    /// replica is offline, so the write commits locally and the call surfaces
    /// the failed push; the committed row is what this test reads.
    #[tokio::test]
    async fn an_admin_session_mints_a_consumer_key_for_an_owner() {
        let (app, db, admin, customer) = app().await;

        let (status, body) = call_session(
            app.clone(),
            "POST",
            CREATE,
            &admin,
            Some(r#"{"tier":"commercial","owner":"utmelab-app"}"#),
        )
        .await;
        assert_eq!(status, StatusCode::BAD_GATEWAY, "{body}");

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
