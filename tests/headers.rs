//! R6 + R9: rate-limit introspection and ETag/304 caching.
//!
//! These guard the contract an integrator codes against: the headers exist,
//! they agree with the budget, and a matching `If-None-Match` actually yields
//! a 304 instead of a full body.

use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::http::{Request, StatusCode};
use tower::ServiceExt;
use utmelab_api::{AppState, JsonStore, KeyBackend, KeyStore, RateLimiter, ReportStore, router};

fn state() -> AppState {
    let data = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
    let tag = format!("utmelab-headers-{}", std::process::id());
    let keys_path = std::env::temp_dir().join(format!("{tag}-keys.json"));
    let reports_path = std::env::temp_dir().join(format!("{tag}-reports.json"));
    // The key file is deliberately NOT cleared: every request builds a fresh
    // state, so wiping it would delete the very key the request presents.
    let _ = std::fs::remove_file(&reports_path);
    AppState {
        bank: Arc::new(JsonStore::load(&data).expect("bank loads")),
        keys: Arc::new(KeyBackend::file(
            KeyStore::open_json(&keys_path).expect("key store"),
        )),
        limiter: Arc::new(Mutex::new(RateLimiter::new())),
        reports: Arc::new(tokio::sync::Mutex::new(
            ReportStore::open(&reports_path).expect("report store"),
        )),
    }
}

fn key() -> &'static str {
    static KEY: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    KEY.get_or_init(|| {
        let keys_path =
            std::env::temp_dir().join(format!("utmelab-headers-{}-keys.json", std::process::id()));
        let mut keys = KeyStore::open_json(&keys_path).expect("key store");
        keys.create("headers-test", 60).expect("key issued").1
    })
}

async fn call(request: Request<Body>) -> axum::http::Response<axum::body::Body> {
    router(state())
        .oneshot(request)
        .await
        .expect("router responds")
}

fn header<'a>(headers: &'a axum::http::HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|v| v.to_str().ok())
}

#[tokio::test]
async fn a_catalog_get_carries_an_etag_and_cache_control() {
    let response = call(
        Request::builder()
            .uri("/api/v1/exams")
            .body(Body::empty())
            .expect("request"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    let etag = header(response.headers(), "etag").expect("catalog carries an ETag");
    assert!(
        etag.contains('-'),
        "etag is bank_version + uri hash: {etag}"
    );
    assert_eq!(
        header(response.headers(), "cache-control"),
        Some("public, max-age=3600"),
        "the catalog changes on import, not on request"
    );
}

#[tokio::test]
async fn a_matching_if_none_match_is_a_304_without_a_body() {
    let first = call(
        Request::builder()
            .uri("/api/v1/exams")
            .body(Body::empty())
            .expect("request"),
    )
    .await;
    let etag = header(first.headers(), "etag").expect("etag").to_owned();

    let second = call(
        Request::builder()
            .uri("/api/v1/exams")
            .header("if-none-match", &etag)
            .body(Body::empty())
            .expect("request"),
    )
    .await;
    assert_eq!(second.status(), StatusCode::NOT_MODIFIED);
    assert_eq!(header(second.headers(), "etag"), Some(etag.as_str()));

    let bytes = axum::body::to_bytes(second.into_body(), 64 * 1024)
        .await
        .expect("body");
    assert!(bytes.is_empty(), "a 304 carries no body");
}

#[tokio::test]
async fn a_different_query_is_a_different_etag() {
    let one = call(
        Request::builder()
            .uri("/api/v1/questions?subject=biology")
            .header("x-api-key", key())
            .body(Body::empty())
            .expect("request"),
    )
    .await;
    let two = call(
        Request::builder()
            .uri("/api/v1/questions?subject=chemistry")
            .header("x-api-key", key())
            .body(Body::empty())
            .expect("request"),
    )
    .await;
    let etag_one = header(one.headers(), "etag").expect("etag one");
    let etag_two = header(two.headers(), "etag").expect("etag two");
    assert_ne!(
        etag_one, etag_two,
        "the same bank version, different filter — a shared etag would 304 a changed query"
    );
    assert_eq!(
        header(one.headers(), "cache-control"),
        Some("public, max-age=60"),
        "questions grow on merge, so a minute of staleness"
    );
}

#[tokio::test]
async fn an_authenticated_response_reports_the_rate_budget() {
    let response = call(
        Request::builder()
            .uri("/api/v1/questions?per_page=1")
            .header("x-api-key", key())
            .body(Body::empty())
            .expect("request"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);

    assert_eq!(header(response.headers(), "x-ratelimit-limit"), Some("60"));
    assert_eq!(
        header(response.headers(), "x-ratelimit-remaining"),
        Some("59"),
        "this request spent one token; the budget reported includes it"
    );
    assert_eq!(header(response.headers(), "x-ratelimit-reset"), Some("0"));
}

#[tokio::test]
async fn an_unauthenticated_response_carries_no_budget_headers() {
    let response = call(
        Request::builder()
            .uri("/api/v1/exams")
            .body(Body::empty())
            .expect("request"),
    )
    .await;
    assert_eq!(response.status(), StatusCode::OK);
    assert!(
        header(response.headers(), "x-ratelimit-limit").is_none(),
        "no key, no budget to report"
    );
}

#[tokio::test]
async fn health_and_keys_me_are_excluded_from_caching() {
    for path in ["/health", "/api/v1/keys/me"] {
        let mut builder = Request::builder().uri(path);
        if path.contains("keys/me") {
            builder = builder.header("x-api-key", key());
        }
        let response = call(builder.body(Body::empty()).expect("request")).await;
        assert!(
            header(response.headers(), "etag").is_none(),
            "{path} must not be cached: /health is polled whole, /keys/me is per-key"
        );
    }
}
