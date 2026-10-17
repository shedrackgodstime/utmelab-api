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

use axum::{middleware::from_fn_with_state, routing::post, Router};

use crate::{auth::api_key::verify_key, config::Config, state::AppState};

pub fn router(state: AppState, cfg: &Config) -> Router<AppState> {
    // Same split as `api`: `verify_key` rides inside the budget of the group
    // it guards, so the gate is bounded like the work behind it.
    let reads = Router::new()
        .route("/mcp/tools/list_tables", post(tools::list_tables))
        .layer(from_fn_with_state(state.clone(), verify_key))
        .layer(cfg.fast_timeout());
    let writes = Router::new()
        .route("/mcp/tools/revoke_key", post(tools::revoke_key))
        .route("/mcp/tools/unrevoke_key", post(tools::unrevoke_key))
        .layer(from_fn_with_state(state.clone(), verify_key))
        .layer(cfg.slow_timeout());
    reads.merge(writes).with_state(state)
}
