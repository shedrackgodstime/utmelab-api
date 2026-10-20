//! v1 of the public API. When a breaking change arrives this becomes a sibling
//! `api/v2/` directory — never a feature flag inside v1 (D25).

use axum::Router;

use crate::AppState;

pub mod blueprints;
pub mod exams;
pub mod keys;
pub mod novels;
pub mod papers;
pub mod passages;
pub mod questions;
pub mod reports;
pub mod subjects;
pub mod topics;

pub fn router() -> Router<AppState> {
    Router::new()
        .merge(exams::router())
        .merge(subjects::router())
        .merge(questions::router())
        .merge(keys::router())
        .merge(novels::router())
        .merge(papers::router())
        .merge(reports::router())
        .merge(passages::router())
        .merge(topics::router())
        .merge(blueprints::router())
}
