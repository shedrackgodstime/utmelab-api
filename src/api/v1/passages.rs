//! `/api/v1/passages/{id}` — fetch a shared stimulus.
//!
//! Questions carry `passage_id`; without this route that reference dangles.
//! Public: a passage is content to read, not answers to protect.

use axum::Json;
use axum::Router;
use axum::extract::{Path, State};
use axum::routing::get;
use serde::Serialize;
use utoipa::ToSchema;

use crate::AppState;
use crate::bank::Passage;
use crate::error::ApiError;

#[derive(Serialize, ToSchema)]
pub struct PassageEnvelope {
    pub passage: Passage,
}

pub fn router() -> Router<AppState> {
    Router::new().route("/v1/passages/{id}", get(passage))
}

#[utoipa::path(
    get,
    path = "/api/v1/passages/{id}",
    tag = "catalog",
    operation_id = "getPassage",
    description = "One shared stimulus — a comprehension or cloze passage its questions point at.",
    params(("id" = String, Path, description = "Passage id.")),
    responses(
        (status = 200, body = PassageEnvelope),
        (status = 404, description = "No such passage"),
    ),
)]
pub async fn passage(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<PassageEnvelope>, ApiError> {
    let bank = state.bank.borrow().clone();
    bank.passage(&id)
        .map(|p| Json(PassageEnvelope { passage: p.clone() }))
        .ok_or_else(|| {
            ApiError::not_found("passage_not_found", format!("No passage with id '{id}'."))
        })
}
