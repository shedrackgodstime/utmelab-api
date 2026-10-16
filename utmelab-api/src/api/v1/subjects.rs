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

pub async fn by_exam(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(exam): Path<String>,
) -> Result<Json<Vec<core::models::Subject>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(store::catalog::list_subjects(&s, &exam).await?))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/exams/{exam}/subjects", get(by_exam))
        .with_state(state)
}
