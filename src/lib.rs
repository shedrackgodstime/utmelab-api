//! Small crate docs live here: one Axum process, three surfaces
//! (`api`, `mcp`, `internal`) merged in [`routes`], one gated Turso replica
//! in [`store`], pure logic in [`core`].
//!
//! Rules: surfaces never import each other; `core` imports neither axum
//! nor turso; `turso` is imported only by `store`; every handler returns
//! [`error::AppError`].

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
