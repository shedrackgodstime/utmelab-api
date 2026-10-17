//! MCP resources — reserved, no resources yet.
//!
//! Resources will be URI-addressed, read-only views over `AppState` (catalog,
//! exams, questions by id). First resources land after the auth decision.

use axum::Router;

use crate::AppState;

/// Empty router. Each resource registers here as it lands.
pub fn router() -> Router<AppState> {
    Router::new()
}
