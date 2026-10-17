//! MCP surface.
//!
//! Built today: three admin tools (`list_tables`, `revoke_key`,
//! `unrevoke_key`) that call the same `store` functions the HTTP handlers
//! use, so the scope and audit rules hold on both surfaces.
//!
//! Planned, not built (the release after this one ships): the `resources`
//! surface (see `resources.rs`) and the read tools that mirror the catalog.
//! Until those land, MCP is a strict subset of HTTP, not a parity of it. Do
//! not add a second auth for an admin op HTTP already gates.

pub mod resources;
pub mod tools;

use axum::{routing::post, Router};

use crate::{config::Config, state::AppState};

pub fn router(state: AppState, cfg: &Config) -> Router<AppState> {
    Router::new()
        .route(
            "/mcp/tools/list_tables",
            post(tools::list_tables).route_layer(cfg.fast_timeout()),
        )
        .route(
            "/mcp/tools/revoke_key",
            post(tools::revoke_key).route_layer(cfg.slow_timeout()),
        )
        .route(
            "/mcp/tools/unrevoke_key",
            post(tools::unrevoke_key).route_layer(cfg.slow_timeout()),
        )
        .with_state(state)
}
