//! MCP tools: the actions (POST on the HTTP surface), at `/mcp/tools/<verb>_<noun>`.
//!
//! The admin tools (`revoke_key`, `unrevoke_key`) are the one place MCP needs
//! its own handler: they call the same `store` call the dashboard uses, so the
//! capability, scope, and audit hold on both surfaces. Every other tool mounts
//! the HTTP handler itself (the reports and papers writes), for the same
//! no-drift reason the resources do.

use axum::{extract::State, routing::post, Json, Router};

use crate::{
    api::v1::{papers, reports},
    auth::{api_key::AuthedKey, Auth, SCOPE_MANAGE_KEYS},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/mcp/tools/revoke_key", post(revoke_key))
        .route("/mcp/tools/unrevoke_key", post(unrevoke_key))
        .route("/mcp/tools/file_report", post(reports::file))
        .route(
            "/mcp/tools/assemble_paper/{exam}/{subject}",
            post(papers::assemble_paper),
        )
        .route(
            "/mcp/tools/score_paper/{exam}/{subject}",
            post(papers::score_paper),
        )
}

/// Admin-only. Same core path as the dashboard revoke — one operation,
/// two surfaces.
pub async fn revoke_key(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Json(b): Json<core::models::PrefixBody>,
) -> Result<Json<core::models::Applied>, AppError> {
    apply(&s, &auth, &b.prefix, true).await
}

pub async fn unrevoke_key(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Json(b): Json<core::models::PrefixBody>,
) -> Result<Json<core::models::Applied>, AppError> {
    apply(&s, &auth, &b.prefix, false).await
}

/// The body both revoke tools share; they differ only by the flag. The actor
/// is the presenting key, so the audit line names it.
async fn apply(
    s: &DbState,
    auth: &Auth,
    prefix: &str,
    revoked: bool,
) -> Result<Json<core::models::Applied>, AppError> {
    auth.require(SCOPE_MANAGE_KEYS)?;
    let actor = format!("key:{}", auth.key_id);
    let ok = store::accounts::set_revoked(s, prefix, revoked, &actor).await?;
    Ok(Json(core::models::Applied { ok }))
}
