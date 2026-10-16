use axum::{
    extract::{Path, Query, State},
    routing::get,
    Json, Router,
};
use serde::Deserialize;

use crate::{
    auth::{api_key::AuthedKey, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

pub async fn tables(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
) -> Result<Json<Vec<core::models::TableRef>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(store::catalog::table_refs(&s).await?))
}

#[derive(Deserialize)]
pub struct RowsParams {
    pub limit: Option<u64>,
}

pub async fn rows(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(table): Path<String>,
    Query(q): Query<RowsParams>,
) -> Result<Json<core::models::RowPage>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(
        store::catalog::fetch_rows(&s, &table, q.limit.unwrap_or(20)).await?,
    ))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/meta/tables", get(tables))
        .route("/v1/meta/rows/{table}", get(rows))
        .with_state(state)
}
