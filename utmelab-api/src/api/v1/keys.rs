use axum::{routing::get, Json, Router};

use crate::{auth::api_key::AuthedKey, core, error::AppError, state::AppState};

pub async fn me(AuthedKey(auth): AuthedKey) -> Result<Json<core::models::KeyInfo>, AppError> {
    Ok(Json(core::models::KeyInfo {
        prefix: auth.key_id,
        admin: auth.is_admin,
        scopes: auth.scopes,
    }))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/keys/me", get(me))
        .with_state(state)
}
