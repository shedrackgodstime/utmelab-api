//! ▸ MCP (Model Context Protocol) surface — prototype scaffold.
//!
//! Lives in `src/` (no `crates/` — the tree has not grown into a workspace
//! yet). No behaviour here yet: this module only reserves the shape
//! (`auth`, `tools`, `resources`) so the auth decision lands first and every
//! later tool has one place to live.
//!
//! Two auth methods are planned (decision pending): the commercial API key
//! (same `Caller` rules as `/api/v1`) and an admin/dev credential. Nothing
//! is enforced until that decision row exists.

pub mod auth;
pub mod resources;
pub mod tools;

use axum::Router;

use crate::AppState;

/// Empty router. Tool/resource routes merge here as they land.
pub fn router() -> Router<AppState> {
    Router::new()
        .merge(tools::router())
        .merge(resources::router())
}
