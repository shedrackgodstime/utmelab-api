//! Composition root: merges the surfaces plus `/health` and applies the
//! global layers. Surface-specific layers live with their surface; only
//! transport-agnostic limits live here. Time budgets come from `Config`
//! so surfaces never import each other for them.
//!
//! URL policy: `/api/*` (v1 commercial reads, internal dashboard/admin)
//! nests here so local and prod paths are identical — no proxy prefix
//! magic. `/mcp/*` and `/health` stay top-level.

pub mod health;

use axum::{
    body::Body,
    extract::State,
    http::Request,
    middleware::Next,
    response::{IntoResponse, Response},
    routing::get,
    Router,
};
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

/// Fail closed while the sync task reports a schema contract mismatch. The
/// replica's shape is then not the one this build reads, so answering would
/// mean serving rows we cannot trust; the log already says "refusing to trust
/// replica", and this is what makes that true. `/health` stays outside the
/// guard so liveness is independent of the database.
async fn contract_guard(
    State(state): State<AppState>,
    request: Request<Body>,
    next: Next,
) -> Response {
    if !state.contract_ok.load(std::sync::atomic::Ordering::Relaxed) {
        return AppError::SchemaMismatch.into_response();
    }
    next.run(request).await
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
    // Every data surface sits behind the contract guard; only `/health`
    // stays public, and it carries no database.
    let gated = Router::new()
        .nest("/api", api)
        .merge(mcp::router(state.clone(), cfg))
        .layer(axum::middleware::from_fn_with_state(
            state.clone(),
            contract_guard,
        ));
    Router::new()
        .route(
            "/health",
            get(health::health).route_layer(cfg.fast_timeout()),
        )
        .merge(gated)
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
            // 16 KiB is ~5x our largest body (a 40-answer paper score). A
            // JSON bomb dies at the edge, not in serde.
            axum::extract::DefaultBodyLimit::max(16 * 1024),
            ConcurrencyLimitLayer::new(cfg.concurrency_limit),
            // Outermost by construction, so it is the net every route falls
            // back on: a route that forgets its own budget still cannot run
            // forever and hold a DB permit. Read routes layer 5s inside this.
            cfg.slow_timeout(),
        ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use tower::ServiceExt;

    fn state(contract_ok: bool) -> AppState {
        AppState {
            name: Arc::from("test"),
            db: Arc::new(tokio::sync::RwLock::new(None)),
            db_gate: Arc::new(tokio::sync::Semaphore::new(1)),
            conns: Arc::new(crate::store::ConnPool::new(1)),
            metrics: Arc::new(crate::state::Metrics::default()),
            cookie_secure: false,
            write_mutex: Arc::new(tokio::sync::Mutex::new(())),
            contract_ok: Arc::new(std::sync::atomic::AtomicBool::new(contract_ok)),
            limiter: Arc::new(crate::auth::rate_limit::RateLimiter::new()),
        }
    }

    async fn probe(contract_ok: bool) -> (axum::http::StatusCode, String) {
        let app = Router::new()
            .route("/data", get(|| async { "payload" }))
            .layer(axum::middleware::from_fn_with_state(
                state(contract_ok),
                contract_guard,
            ));
        let res = app
            .oneshot(
                Request::builder()
                    .uri("/data")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("router call");
        let status = res.status();
        let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
            .await
            .expect("body");
        (status, String::from_utf8(bytes.to_vec()).expect("utf8"))
    }

    #[tokio::test]
    async fn contract_guard_fails_closed_on_mismatch() {
        let (status, body) = probe(false).await;
        assert_eq!(status, axum::http::StatusCode::SERVICE_UNAVAILABLE);
        assert!(body.contains("schema_mismatch"), "{body}");
        assert!(!body.contains("payload"), "body leaked past the guard");
    }

    #[tokio::test]
    async fn contract_guard_passes_when_trusted() {
        let (status, body) = probe(true).await;
        assert_eq!(status, axum::http::StatusCode::OK);
        assert_eq!(body, "payload");
    }
}
