//! MCP tools — reserved, no tools yet.
//!
//! Tools will be thin projections over `AppState` (the same `Store` reads
//! the routes already call). First tools land after the auth decision.

use axum::Router;

use crate::AppState;

/// Empty router. Each tool registers here as it lands.
pub fn router() -> Router<AppState> {
    Router::new()
}
