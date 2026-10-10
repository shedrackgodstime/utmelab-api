//! utmelab-api — the question bank as a public, metered API.
//!
//! One API tier over a shared core. The **web tier is static files** (D32) — Astro
//! builds a directory of HTML that Caddy serves; there is no Node process and no
//! SSR.
//!
//! ```text
//!   src/api/   ▸ /api/v1/*      sold, API-key auth, in the public OpenAPI spec
//!             ▸ /internal/v1/* dashboard-only, session auth, never in the spec (D33)
//!   src/bank/  ▸ the content core. No HTTP anywhere in it, so the API and the
//!                       static web tier can read it without either reshaping it.
//!   src/keys/  ▸ API keys. Separate lifecycle from published content.
//! ```
//!
//! The boundary is the point. `bank/` knows nothing about requests; `api/` knows
//! nothing about storage. That is what makes D23's promise keepable — when Turso
//! arrives, `bank::JsonStore` gains a sibling and no route moves.
//!
//! **Deployment is two artifacts:** this binary, and `web/dist` served as files.

pub mod api;
mod bank;
mod config;
mod error;
mod keys;
mod reports;

pub use api::auth::Caller;
pub use api::limit::RateLimiter;
pub use api::openapi::document as openapi_document;

pub use bank::{DEFAULT_PER_PAGE, JsonStore, MAX_PER_PAGE, QuestionFilter, Store, StoreError};
pub use config::Config;
pub use error::ApiError;
pub use keys::{ApiKey, KeyStore};
pub use reports::{QuestionReport, ReportReason, ReportStore};

use axum::Json;
use axum::Router;
use axum::extract::State;
use axum::routing::get;
use serde::Serialize;
use std::sync::{Arc, Mutex};

/// Everything a handler may read. The bank is behind `dyn Store` so swapping
/// the backing store never reaches the routes.
#[derive(Clone)]
pub struct AppState {
    pub bank: Arc<dyn Store>,
    pub keys: KeyStore,
    /// Behind an `Arc<Mutex<…>>` because axum requires `Clone` state but the
    /// limiter is mutable — one lock held for a few arithmetic operations.
    pub limiter: Arc<Mutex<RateLimiter>>,
    /// Report store. Same pattern: mutable, shared, locked per call.
    pub reports: Arc<Mutex<ReportStore>>,
}

#[derive(Serialize)]
struct Health {
    status: &'static str,
    service: &'static str,
    version: &'static str,
    subjects: usize,
    questions: usize,
    /// Records present but not servable. Never silent.
    withheld: usize,
}

/// One router. Caddy path-routes `/api/*` here and everything else to the static
/// web tier (D32), so this process never serves HTML.
pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .merge(api::router())
        .fallback(not_found)
        .with_state(state)
}

async fn health(State(state): State<AppState>) -> Json<Health> {
    Json(Health {
        status: "ok",
        service: "utmelab-api",
        version: env!("CARGO_PKG_VERSION"),
        subjects: state.bank.subject_count(),
        questions: state.bank.question_count(),
        withheld: state.bank.withheld_count(),
    })
}

async fn not_found() -> ApiError {
    ApiError::not_found("route_not_found", "No such endpoint.")
}
