use axum::{extract::State, routing::get, Json, Router};

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
) -> Result<Json<Vec<core::models::Exam>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(store::catalog::list_exams(&s).await?))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/exams", get(list))
        .with_state(state)
}
