//! Public HTTP router. Merges versioned routers; surface-wide HTTP layers
//! attach here, global limits stay in `routes`.
//!
//! CORS is permissive on purpose: browser apps call us directly, and the
//! key is extractable from any client anyway, so a wildcard origin adds
//! no exposure the key model did not already accept. Credentials stay
//! off; the key travels in a header, never a cookie.

pub mod middleware;
pub mod v1;

use axum::{middleware::from_fn, Router};
use tower_http::cors::{AllowHeaders, AllowMethods, AllowOrigin, CorsLayer, ExposeHeaders};

use crate::{config::Config, state::AppState};

pub fn router(state: AppState, cfg: &Config) -> Router<AppState> {
    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::any())
        .allow_methods(AllowMethods::list([
            axum::http::Method::GET,
            axum::http::Method::POST,
        ]))
        .allow_headers(AllowHeaders::list([
            axum::http::HeaderName::from_static("x-api-key"),
            axum::http::header::CONTENT_TYPE,
            axum::http::header::ACCEPT,
            axum::http::header::AUTHORIZATION,
        ]))
        .expose_headers(ExposeHeaders::list([
            axum::http::header::RETRY_AFTER,
            axum::http::header::CONTENT_TYPE,
        ]));
    // Reads run on the read budget and carry ETag; the report routes write
    // (they push to the cloud), so they sit outside both and take the global
    // write budget from `routes`. Same split as `internal` and `mcp`, where
    // the verb, not the path, picks the budget.
    let reads = v1::router(state.clone())
        .layer(from_fn(middleware::etag))
        .layer(cfg.fast_timeout());
    let writes = v1::reports::router(state);
    Router::new().merge(reads).merge(writes).layer(cors)
}
