mod cpu;
mod db;
mod health;
mod slow;

use std::time::Duration;

use axum::{http::StatusCode, routing::get, Router};
use tower::limit::ConcurrencyLimitLayer;
use tower_http::{
    compression::CompressionLayer,
    limit::RequestBodyLimitLayer,
    timeout::TimeoutLayer,
    trace::{DefaultOnFailure, TraceLayer},
};
use tracing::Level;

use crate::{config::Config, state::AppState};

pub fn build_router(state: AppState, cfg: Config) -> Router {
    let fast = Router::new()
        .route("/health", get(health::health))
        .route("/json", get(health::json_health))
        .route("/slow", get(slow::slow))
        .with_state(state.clone());

    let big = Router::new()
        .route("/cpu", get(cpu::cpu_work))
        .route_layer(CompressionLayer::new())
        .with_state(state.clone());

    let data = Router::new()
        .route("/db-remote", get(db::db_remote))
        .route("/db-sync", get(db::db_sync))
        .with_state(state);

    Router::new().merge(fast).merge(big).merge(data).layer((
        TraceLayer::new_for_http().on_failure(DefaultOnFailure::new().level(Level::WARN)),
        RequestBodyLimitLayer::new(16 * 1024),
        ConcurrencyLimitLayer::new(cfg.concurrency_limit),
        TimeoutLayer::with_status_code(StatusCode::REQUEST_TIMEOUT, Duration::from_secs(5)),
    ))
}
