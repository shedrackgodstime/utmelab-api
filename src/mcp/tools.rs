use axum::{extract::State, Json};

use crate::{
    auth::{api_key::AuthedKey, SCOPE_MANAGE_KEYS, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::DbState,
    store,
};

pub async fn list_tables(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
) -> Result<Json<Vec<core::models::TableRef>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(store::catalog::table_refs(&s).await?))
}

/// Admin-only. Same core path as the dashboard revoke — one operation,
/// two surfaces.
pub async fn revoke_key(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Json(b): Json<core::models::PrefixBody>,
) -> Result<Json<serde_json::Value>, AppError> {
    auth.require(SCOPE_MANAGE_KEYS)?;
    let actor = format!("key:{}", auth.key_id);
    let found = store::accounts::set_revoked(&s, &b.prefix, true, &actor).await?;
    Ok(Json(serde_json::json!({"ok": found})))
}

pub async fn unrevoke_key(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Json(b): Json<core::models::PrefixBody>,
) -> Result<Json<serde_json::Value>, AppError> {
    auth.require(SCOPE_MANAGE_KEYS)?;
    let actor = format!("key:{}", auth.key_id);
    let found = store::accounts::set_revoked(&s, &b.prefix, false, &actor).await?;
    Ok(Json(serde_json::json!({"ok": found})))
}
