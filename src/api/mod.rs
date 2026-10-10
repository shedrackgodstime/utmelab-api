//! ▸ The **public commercial API**, served at `/api/v1`.
//!
//! Key-authenticated, JSON, and slow to change — this is a contract we sell.
//! The dashboard lives in `app/` and must never leak in here.

pub mod auth;
pub mod limit;
pub mod openapi;
pub mod v1;

use axum::Router;

use crate::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
        .merge(openapi::router())
        .nest("/api", v1::router())
}
