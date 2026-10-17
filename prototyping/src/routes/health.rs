use axum::{extract::State, Json};
use serde::Serialize;

use crate::state::NameOnly;

#[derive(Serialize)]
pub struct HealthPayload {
    pub status: &'static str,
    pub service: &'static str,
}

pub async fn health(State(state): State<NameOnly>) -> &'static str {
    let _ = &state.name;
    "ok"
}

pub async fn json_health(State(state): State<NameOnly>) -> Json<HealthPayload> {
    let _ = &state.name;
    Json(HealthPayload {
        status: "ok",
        service: "prototype",
    })
}
