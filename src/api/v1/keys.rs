//! `/api/v1/keys/me` — the authentication probe.
//!
//! Returns the calling key exactly as stored. A dedicated projection used to
//! live here that merely renamed two fields; that was duplication with no reason
//! behind it (D22).

use axum::Json;
use axum::Router;
use axum::routing::get;

use crate::AppState;
use crate::api::auth::Caller;
use crate::keys::ApiKey;

pub fn router() -> Router<AppState> {
    Router::new().route("/v1/keys/me", get(me))
}

#[utoipa::path(
    get,
    path = "/api/v1/keys/me",
    tag = "account",
    operation_id = "whoami",
    summary = "The calling key: label, quota, and expiry.",
    description = "Returns the calling key exactly as stored. Use it to check a key works.",
    responses(
        (status = 200, body = ApiKey),
        (status = 401, description = "Missing or invalid API key"),
        (status = 429, description = "Over the key's per-minute limit"),
    ),
    security(("ApiKeyAuth" = [])),
)]
pub async fn me(Caller(key): Caller) -> Json<ApiKey> {
    Json(key)
}
