//! Versioned public API surface. Each domain module owns its routes;
//! shared logic lives in `core`, never duplicated across versions.
pub mod meta;

use axum::Router;

use crate::state::AppState;

pub fn router(state: AppState) -> Router<AppState> {
    Router::new().merge(meta::router(state))
}
