//! Small crate docs live here: one Axum process, three surfaces
//! (`api`, `mcp`, `internal`) merged in [`routes`], one gated Turso replica
//! in [`store`], pure logic in [`core`].
//!
//! Rules: a surface never mounts another surface's router. `mcp` is the one
//! exception to "never import a surface": it shares `api::v1`'s handlers, so a
//! catalog read or an action is written once and cannot drift between the two
//! keyed surfaces. `core` imports neither axum nor turso; `turso` is imported
//! only by `store`; every handler returns [`error::AppError`].

pub mod api;
pub mod auth;
pub mod config;
pub mod core;
pub mod error;
pub mod internal;
pub mod mcp;
pub mod obs;
pub mod routes;
pub mod state;
pub mod store;

#[cfg(test)]
pub(crate) mod testing;
