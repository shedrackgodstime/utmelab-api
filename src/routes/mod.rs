//! Composition root: merges the surfaces plus `/health` (liveness) and
//! `/ready` (readiness) and applies the global layers. Surface-specific
//! layers live with their surface; only transport-agnostic limits live here.
//! Time budgets come from `Config` so surfaces never import each other for
//! them.
//!
//! URL policy: `/api/*` (v1 commercial reads, internal dashboard/admin)
//! nests here so local and prod paths are identical — no proxy prefix
//! magic. `/mcp/*`, `/health` and `/ready` stay top-level. Data surfaces sit
//! behind the contract guard; the two probes do not.

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

/// Latency bucket edges in milliseconds for request telemetry.
const FAST_MS: u64 = 25;
const OK_MS: u64 = 100;

/// Request telemetry: status-class counts, an in-flight gauge, and three
/// latency buckets. Atomics only, so it costs a few increments per request and
/// nothing while idle. Outermost layer, so it times what a client actually
/// waits for; the two probes are skipped so health checks cannot drown out
/// real traffic.
async fn telemetry(State(state): State<AppState>, request: Request<Body>, next: Next) -> Response {
    use std::sync::atomic::Ordering::Relaxed;

    if matches!(request.uri().path(), "/health" | "/ready") {
        return next.run(request).await;
    }
    let m = &state.metrics;
    m.in_flight.fetch_add(1, Relaxed);
    let started = std::time::Instant::now();
    let response = next.run(request).await;
    m.in_flight.fetch_sub(1, Relaxed);

    let status = response.status().as_u16();
    // 408 is our own timeout: a capacity signal, not a client mistake.
    if status >= 500 || status == 408 {
        m.requests_server_error.fetch_add(1, Relaxed);
    } else if status >= 400 {
        m.requests_client_error.fetch_add(1, Relaxed);
    } else {
        m.requests_ok.fetch_add(1, Relaxed);
    }
    let ms = started.elapsed().as_millis() as u64;
    let bucket = if ms < FAST_MS {
        &m.latency_fast
    } else if ms < OK_MS {
        &m.latency_ok
    } else {
        &m.latency_slow
    };
    bucket.fetch_add(1, Relaxed);
    response
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
    let telemetry_state = state.clone();
    Router::new()
        .route(
            "/health",
            get(health::health).route_layer(cfg.fast_timeout()),
        )
        .route("/ready", get(health::ready).route_layer(cfg.fast_timeout()))
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
            // Outermost timeout by construction, so it is the net every route
            // falls back on: a route that forgets its own budget still cannot
            // run forever and hold a DB permit. Read routes layer 5s inside
            // this. Telemetry sits above it and only observes.
            cfg.slow_timeout(),
        ))
        .layer(axum::middleware::from_fn_with_state(
            telemetry_state,
            telemetry,
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

    fn db_state(contract_ok: bool) -> crate::state::DbState {
        crate::state::DbState {
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

    #[tokio::test]
    async fn ready_is_503_until_a_replica_exists() {
        let err = health::ready(State(db_state(true)))
            .await
            .expect_err("no replica yet");
        assert!(matches!(err, AppError::DbUnavailable(_)));
    }

    async fn status_of(app: Router, uri: &'static str) -> axum::http::StatusCode {
        app.oneshot(
            Request::builder()
                .uri(uri)
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("call")
        .status()
    }

    #[tokio::test]
    async fn router_wires_guard_and_telemetry() {
        let st = state(true);
        let metrics = Arc::clone(&st.metrics);
        let app = crate::routes::router(st, &crate::config::Config::default());

        assert_eq!(
            status_of(app.clone(), "/health").await,
            axum::http::StatusCode::OK
        );
        assert_eq!(
            status_of(app.clone(), "/api/v1/meta/tables").await,
            axum::http::StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            status_of(app, "/ready").await,
            axum::http::StatusCode::SERVICE_UNAVAILABLE
        );

        let snap = metrics.snapshot();
        assert_eq!(snap.requests_client_error, 1, "the 401 is counted once");
        assert_eq!(snap.requests_ok, 0, "neither probe is counted");
        assert_eq!(snap.in_flight, 0);
        assert_eq!(snap.latency_fast + snap.latency_ok + snap.latency_slow, 1);
    }

    #[tokio::test]
    async fn router_fails_closed_through_the_guard() {
        let app = crate::routes::router(state(false), &crate::config::Config::default());
        assert_eq!(
            status_of(app.clone(), "/api/v1/meta/tables").await,
            axum::http::StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(status_of(app, "/health").await, axum::http::StatusCode::OK);
    }
}
