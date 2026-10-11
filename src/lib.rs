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
pub mod import;
mod keys;
mod reports;

pub use api::auth::Caller;
pub use api::limit::RateLimiter;
pub use api::openapi::document as openapi_document;

pub use bank::model::Question;
pub use bank::{DEFAULT_PER_PAGE, JsonStore, MAX_PER_PAGE, QuestionFilter, Store, StoreError};
pub use config::Config;
pub use error::ApiError;
pub use keys::{ApiKey, KeyBackend, KeyStatus, KeyStore};
pub use reports::{QuestionReport, ReportReason, ReportStore};

use axum::Json;
use axum::Router;
use axum::extract::State;
use axum::http;
use axum::routing::get;
use serde::Serialize;
use std::sync::{Arc, Mutex};

/// Everything a handler may read. The bank is behind `dyn Store` so swapping
/// the backing store never reaches the routes.
#[derive(Clone)]
pub struct AppState {
    pub bank: Arc<dyn Store>,
    /// File or Turso, chosen at boot (D53). Async because Turso is over the
    /// wire; the file branch is one stat + a lock in the common case (R1:
    /// CLI-created/revoked keys land without a restart).
    pub keys: Arc<KeyBackend>,
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
    /// The binary's version. Changes on deploy.
    version: &'static str,
    /// Fingerprint of the **content** (D42). Changes when a question is added,
    /// edited or withdrawn — never on a deploy that touched no content. A
    /// consumer polls this one endpoint instead of diffing the bank.
    bank_version: String,
    subjects: usize,
    questions: usize,
    /// Records present but not servable. Never silent.
    withheld: usize,
}

/// One router. Caddy path-routes `/api/*` here and everything else to the static
/// web tier (D32), so this process never serves HTML.
///
/// **CORS is `*` (D39).** A browser app must be able to call us directly —
/// D26 already concedes the key is extractable from a client, so a permissive
/// origin adds no exposure that decision did not already accept; the key is
/// still required. Credentials are *not* allowed, because a cookie-bearing
/// wildcard is invalid per spec and we never authenticate by cookie anyway.
pub fn router(state: AppState) -> Router {
    // `x-api-key` is the whole authentication surface — omit it here and every
    // authenticated browser call fails at the preflight, before the key is ever
    // read. That regression is asserted in `tests/cors.rs`.
    let cors = tower_http::cors::CorsLayer::new()
        .allow_origin(tower_http::cors::Any)
        .allow_methods([http::Method::GET, http::Method::POST])
        .allow_headers([
            http::HeaderName::from_static("x-api-key"),
            http::header::CONTENT_TYPE,
            http::header::ACCEPT,
            http::header::AUTHORIZATION,
        ])
        // Without this a browser sees `null` for Retry-After even though it is
        // on the wire (D43).
        .expose_headers([http::header::RETRY_AFTER, http::header::CONTENT_TYPE]);

    Router::new()
        .route("/health", get(health))
        .merge(api::router())
        .fallback(not_found)
        .layer(cors)
        .with_state(state)
}

async fn health(State(state): State<AppState>) -> Json<Health> {
    Json(Health {
        status: "ok",
        service: "utmelab-api",
        version: env!("CARGO_PKG_VERSION"),
        bank_version: state.bank.version().to_owned(),
        subjects: state.bank.subject_count(),
        questions: state.bank.question_count(),
        withheld: state.bank.withheld_count(),
    })
}

async fn not_found() -> ApiError {
    ApiError::not_found("route_not_found", "No such endpoint.")
}
