//! MCP surface. Tools wrap the same `core` functions the HTTP handlers
//! call, so parity is structural; tool-only extras live in `tools`.

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
