//! Admin-only operations. Same core/store calls the MCP admin tools
//! use — one operation, two surfaces, never duplicated.

use axum::{extract::State, Json};

use crate::{auth::session::AdminUser, error::AppError, state::DbState, store};

#[derive(serde::Deserialize)]
pub struct RoleBody {
    pub username: String,
    pub role: String,
}

pub async fn list_users(
    State(s): State<DbState>,
    AdminUser(_u): AdminUser,
) -> Result<Json<Vec<store::accounts::UserSummary>>, AppError> {
    Ok(Json(store::accounts::list_users(&s).await?))
}

pub async fn set_role(
    State(s): State<DbState>,
    AdminUser(_u): AdminUser,
    Json(b): Json<RoleBody>,
) -> Result<Json<serde_json::Value>, AppError> {
    let found = store::accounts::set_user_role(&s, &b.username, &b.role).await?;
    Ok(Json(serde_json::json!({"ok": found})))
}

pub async fn create_admin_key(
    State(s): State<DbState>,
    AdminUser(_u): AdminUser,
) -> Result<Json<serde_json::Value>, AppError> {
    let full = store::accounts::create_admin_key(&s).await?;
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
    AdminUser(_u): AdminUser,
    Json(b): Json<crate::core::models::PrefixBody>,
) -> Result<Json<serde_json::Value>, AppError> {
    let found = store::accounts::set_revoked(&s, &b.prefix, true).await?;
    Ok(Json(serde_json::json!({"ok": found})))
}

pub async fn unrevoke(
    State(s): State<DbState>,
    AdminUser(_u): AdminUser,
    Json(b): Json<crate::core::models::PrefixBody>,
) -> Result<Json<serde_json::Value>, AppError> {
    let found = store::accounts::set_revoked(&s, &b.prefix, false).await?;
    Ok(Json(serde_json::json!({"ok": found})))
}
