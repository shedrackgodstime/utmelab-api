//! Versioned public API surface. Each domain module owns its routes;
//! shared logic lives in `core`, never duplicated across versions.
//!
//! The rules a new endpoint follows, since the code shows examples but
//! not the rule:
//! - Identity: every keyed handler takes `AuthedKey` and calls
//!   `auth.require(SCOPE_*)` before touching the store. The one exception
//!   is an endpoint about the caller's own key (`GET /v1/keys/me`), which
//!   needs no scope. Because the gate lives in the handler, a new route
//!   must also be added to the `KEYED` sweep in `routes`, so the gate is
//!   proven rather than assumed.
//! - Response: return a typed `core::models` struct, never an ad-hoc
//!   `serde_json::json!` value.
//! - Paging: a page is `core::models::Page`, built with `Page::new`, never
//!   a hand-rolled envelope. Clamp inputs with `core::catalog::page_bounds`.
//! - Budget: reads run on the read timeout, writes on the write timeout.
//!   `api` layers the read budget over this router, so a *write* module is
//!   merged outside it (see `reports` in `api::router`).
pub mod blueprints;
pub mod exams;
pub mod keys;
pub mod meta;
pub mod novels;
pub mod papers;
pub mod passages;
pub mod questions;
pub mod reports;
pub mod subjects;
pub mod topics;

use axum::Router;

use crate::state::AppState;

/// Read endpoints. `reports` is deliberately absent: it writes, so
/// `api::router` merges it under the write budget instead.
pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .merge(meta::router(state.clone()))
        .merge(keys::router(state.clone()))
        .merge(novels::router(state.clone()))
        .merge(exams::router(state.clone()))
        .merge(papers::router(state.clone()))
        .merge(subjects::router(state.clone()))
        .merge(topics::router(state.clone()))
        .merge(questions::router(state.clone()))
        .merge(passages::router(state.clone()))
        .merge(blueprints::router(state))
}
