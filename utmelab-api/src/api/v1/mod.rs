//! Versioned public API surface. Each domain module owns its routes;
//! shared logic lives in `core`, never duplicated across versions.
pub mod blueprints;
pub mod exams;
pub mod keys;
pub mod meta;
pub mod novels;
pub mod passages;
pub mod questions;
pub mod reports;
pub mod subjects;
pub mod topics;

use axum::Router;

use crate::state::AppState;

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .merge(meta::router(state.clone()))
        .merge(keys::router(state.clone()))
        .merge(novels::router(state.clone()))
        .merge(exams::router(state.clone()))
        .merge(subjects::router(state.clone()))
        .merge(topics::router(state.clone()))
        .merge(questions::router(state.clone()))
        .merge(passages::router(state.clone()))
        .merge(blueprints::router(state.clone()))
        .merge(reports::router(state))
}
