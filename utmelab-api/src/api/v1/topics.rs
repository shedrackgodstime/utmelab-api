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
    Path((exam, subject, slug)): Path<(String, String, String)>,
) -> Result<Json<core::models::Topic>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match store::catalog::get_topic(&s, &exam, &subject, &slug).await? {
        Some(t) => Ok(Json(t)),
        None => Err(AppError::NotFound),
    }
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/topics/{exam}/{subject}/{slug}", get(one))
        .with_state(state)
}
