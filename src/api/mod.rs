//! Public HTTP router. Merges versioned routers; surface-wide HTTP layers
//! attach here, global limits stay in `routes`.
//!
//! CORS is permissive on purpose: browser apps call us directly, and the
//! key is extractable from any client anyway, so a wildcard origin adds
//! no exposure the key model did not already accept. Credentials stay
//! off; the key travels in a header, never a cookie.

pub mod middleware;
pub mod openapi;
pub mod v1;

use axum::{middleware::from_fn, middleware::from_fn_with_state, Router};
use tower_http::cors::{AllowHeaders, AllowMethods, AllowOrigin, CorsLayer, ExposeHeaders};

use crate::{auth::api_key::verify_key, config::Config, state::AppState};

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
    //
    // `verify_key` rides inside each budget, so key verification is bounded by
    // the same timeout as the work it guards, and outside CORS (applied last
    // below, so a preflight is answered before the gate and never needs a key).
    let reads = v1::router(state.clone())
        .layer(from_fn_with_state(state.clone(), verify_key))
        .layer(from_fn(middleware::etag))
        .layer(cfg.fast_timeout());
    // The discovery surface is the one place with no key to verify, so it is
    // mounted without `verify_key`; an IP ceiling stands in for the quota a key
    // would otherwise carry. Keeping it a separate router is what makes the
    // divide structural rather than a property of each handler.
    let public = v1::public::router(state.clone())
        .layer(from_fn_with_state(state.clone(), middleware::public_limit))
        .layer(from_fn(middleware::etag))
        .layer(from_fn(middleware::public_cache))
        .layer(cfg.fast_timeout());
    let writes =
        v1::reports::router(state.clone()).layer(from_fn_with_state(state.clone(), verify_key));
    Router::new()
        .merge(reads)
        .merge(public)
        .merge(writes)
        .layer(cors)
}

#[cfg(test)]
mod tests {
    use axum::http::{header, Request, StatusCode};
    use tower::ServiceExt;

    /// A CORS preflight carries no key. CORS is the outermost layer, so the
    /// `verify_key` gate never sees it: a browser's OPTIONS must be answered,
    /// not refused. The stateless app proves the layer stack alone decides it,
    /// since a gate that ran would fail on the absent replica.
    #[tokio::test]
    async fn cors_preflight_is_answered_before_the_key_gate() {
        let app = crate::routes::router(
            crate::testing::state_without_db(true),
            &crate::config::Config::default(),
        );
        let req = Request::builder()
            .method("OPTIONS")
            .uri("/api/v1/questions")
            .header(header::ORIGIN, "https://app.example")
            .header(header::ACCESS_CONTROL_REQUEST_METHOD, "GET")
            .header(header::ACCESS_CONTROL_REQUEST_HEADERS, "x-api-key")
            .body(axum::body::Body::empty())
            .expect("request");
        let res = app.oneshot(req).await.expect("preflight");
        assert_eq!(res.status(), StatusCode::OK);
        assert!(
            res.headers()
                .contains_key(header::ACCESS_CONTROL_ALLOW_ORIGIN),
            "the preflight must be answered, not gated"
        );
    }
}
