//! ▸ `/internal/*` — dashboard-only endpoints. **Unversioned by design.**
//!
//! These are us talking to ourselves: the dashboard's account, usage and
//! billing reads. They must **never** appear in the public OpenAPI spec, carry
//! no version prefix (they have no external consumers to break), and are
//! authenticated by session cookie — not API key (D33).
//!
//! Empty until the dashboard needs its first endpoint. When that lands it goes
//! here, never under `/api/v1/`.

use axum::Router;

use crate::AppState;

pub fn router() -> Router<AppState> {
    Router::new()
    // First endpoint lands here when the dashboard needs it.
    // Intentionally absent from `openapi.rs`.
}
