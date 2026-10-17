use axum::{extract::State, Json};

use crate::{
    auth::{api_key::AuthedKey, Auth, SCOPE_MANAGE_KEYS, SCOPE_READ_CATALOG},
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
