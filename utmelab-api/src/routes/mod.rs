//! Composition root: merges the surfaces plus `/health` and applies the
//! global layers. Surface-specific layers live with their surface; only
//! transport-agnostic limits live here. Time budgets come from `Config`
//! so surfaces never import each other for them.
//!
//! URL policy: `/api/*` (v1 commercial reads, internal dashboard/admin)
//! nests here so local and prod paths are identical — no proxy prefix
//! magic. `/mcp/*` and `/health` stay top-level.

pub mod health;

use axum::{body::Body, http::Request, routing::get, Router};
use tower::limit::ConcurrencyLimitLayer;
use tower_http::{
    request_id::{MakeRequestUuid, PropagateRequestIdLayer, SetRequestIdLayer},
    trace::{DefaultOnFailure, TraceLayer},
};
use tracing::Level;

use crate::{api, config::Config, error::AppError, internal, mcp, state::AppState};

const REQUEST_ID: &str = "x-request-id";

async fn not_found() -> AppError {
    AppError::NotFound
}

fn span_for(request: &Request<Body>) -> tracing::Span {
    let id = request
        .headers()
        .get(REQUEST_ID)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("none")
        .to_string();
    tracing::info_span!("request", id, method = %request.method(), path = %request.uri().path())
}

pub fn router(state: AppState, cfg: &Config) -> Router {
    let api = Router::new()
        .merge(api::router(state.clone(), cfg))
        .merge(internal::router(state.clone(), cfg));
    Router::new()
        .route(
            "/health",
            get(health::health).route_layer(cfg.fast_timeout()),
        )
        .nest("/api", api)
        .merge(mcp::router(state.clone(), cfg))
        .fallback(not_found)
        .with_state(state)
        .layer((
            SetRequestIdLayer::new(
                axum::http::HeaderName::from_static(REQUEST_ID),
                MakeRequestUuid,
            ),
            TraceLayer::new_for_http()
                .make_span_with(span_for)
                .on_failure(DefaultOnFailure::new().level(Level::WARN)),
            PropagateRequestIdLayer::new(axum::http::HeaderName::from_static(REQUEST_ID)),
            axum::extract::DefaultBodyLimit::max(64 * 1024),
            ConcurrencyLimitLayer::new(cfg.concurrency_limit),
        ))
}
