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

pub async fn list(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject)): Path<(String, String)>,
) -> Result<Json<Vec<core::models::Blueprint>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(
        store::catalog::list_blueprints(&s, &exam, &subject).await?,
    ))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/blueprints/{exam}/{subject}", get(list))
        .with_state(state)
}
