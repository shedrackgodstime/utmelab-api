use axum::{
    extract::{Path, State},
    routing::get,
    Json, Router,
};

use crate::{
    auth::{api_key::AuthedKey, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

pub async fn one(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
) -> Result<Json<core::models::Passage>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match store::catalog::get_passage(&s, &id).await? {
        Some(p) => Ok(Json(p)),
        None => Err(AppError::NotFound),
    }
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/passages/{id}", get(one))
        .with_state(state)
}
