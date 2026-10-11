//! A browser must be able to call us directly (D39).
//!
//! The failure these guard against is invisible to `curl` and to our own app: a
//! browser sends a **preflight** `OPTIONS` before any cross-origin request
//! carrying `X-API-Key`, and if that preflight is not answered the real request
//! is never sent — the key is rejected by the browser before it reaches us.
//!
//! So these assert the preflight a browser actually performs, and the header on
//! the response the browser then reads.

use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::http::{HeaderMap, Method, Request, StatusCode};
use tower::ServiceExt;
use utmelab_api::{AppState, JsonStore, KeyStore, RateLimiter, ReportStore, router};

fn state() -> AppState {
    let data = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
    let tag = format!("utmelab-cors-{}", std::process::id());
    let keys_path = std::env::temp_dir().join(format!("{tag}-keys.json"));
    let reports_path = std::env::temp_dir().join(format!("{tag}-reports.json"));
    let _ = std::fs::remove_file(&keys_path);
    let _ = std::fs::remove_file(&reports_path);
    AppState {
        bank: Arc::new(JsonStore::load(&data).expect("bank loads")),
        keys: KeyStore::open_json(&keys_path).expect("key store"),
        limiter: Arc::new(Mutex::new(RateLimiter::new())),
        reports: Arc::new(Mutex::new(
            ReportStore::open(&reports_path).expect("report store"),
        )),
    }
}

/// The request a browser makes before sending a keyed cross-origin GET.
fn preflight(path: &str) -> Request<Body> {
    Request::builder()
        .method(Method::OPTIONS)
        .uri(path)
        .header("origin", "https://app.utmelab.com")
        .header("access-control-request-method", "GET")
        .header("access-control-request-headers", "x-api-key")
        .body(Body::empty())
        .expect("preflight request")
}

fn header<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|v| v.to_str().ok())
}

#[tokio::test]
async fn the_preflight_a_browser_sends_is_answered() {
    let response = router(state())
        .oneshot(preflight("/api/v1/questions"))
        .await
        .expect("router responds");

    assert!(
        response.status().is_success(),
        "a failed preflight means the browser never sends the real request"
    );

    let allow_origin = header(response.headers(), "access-control-allow-origin")
        .expect("preflight must grant the origin");
    assert!(
        allow_origin == "*" || allow_origin == "https://app.utmelab.com",
        "unexpected allow-origin: {allow_origin}"
    );

    assert_eq!(
        header(response.headers(), "access-control-allow-methods"),
        Some("GET,POST"),
        "GET and POST are our whole surface"
    );

    let allowed = header(response.headers(), "access-control-allow-headers")
        .unwrap_or_default()
        .to_lowercase();
    assert!(
        allowed.contains("x-api-key"),
        "the key header must be permitted, or every authenticated call fails: {allowed}"
    );
    assert!(
        allowed.contains("content-type"),
        "reports send JSON bodies, so content-type must be permitted too: {allowed}"
    );
}

#[tokio::test]
async fn a_cross_origin_get_carries_the_grant_and_exposes_retry_after() {
    let req = Request::builder()
        .method(Method::GET)
        .uri("/api/v1/exams")
        .header("origin", "https://app.utmelab.com")
        .body(Body::empty())
        .expect("request");

    let response = router(state()).oneshot(req).await.expect("responds");
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        header(response.headers(), "access-control-allow-origin"),
        Some("*"),
        "the actual response, not just the preflight, must grant the origin"
    );
}

#[tokio::test]
async fn retry_after_is_readable_by_browser_javascript() {
    // Without `expose-headers`, a browser client sees null for Retry-After even
    // though the header is on the wire — D43 would be invisible to exactly the
    // consumers D39 exists to unblock.
    let req = Request::builder()
        .method(Method::GET)
        .uri("/api/v1/questions")
        .header("origin", "https://app.utmelab.com")
        .header("x-api-key", "not-a-real-key")
        .body(Body::empty())
        .expect("request");

    let response = router(state()).oneshot(req).await.expect("responds");
    let exposed = header(response.headers(), "access-control-expose-headers")
        .unwrap_or_default()
        .to_lowercase();
    assert!(
        exposed.contains("retry-after"),
        "Retry-After must be exposed to JS: {exposed}"
    );
}

#[tokio::test]
async fn credentialed_requests_are_not_wildcarded() {
    // A wildcard origin with credentials is invalid per the CORS spec and a
    // classic source of silently-dropped cookies. We authenticate by key, never
    // by cookie, so credentials stay off.
    let req = Request::builder()
        .method(Method::GET)
        .uri("/api/v1/exams")
        .header("origin", "https://app.utmelab.com")
        .body(Body::empty())
        .expect("request");

    let response = router(state()).oneshot(req).await.expect("responds");
    assert_ne!(
        header(response.headers(), "access-control-allow-credentials"),
        Some("true"),
        "we must not opt into credentialed cross-origin requests"
    );
}

#[tokio::test]
async fn a_same_origin_call_is_unaffected() {
    let req = Request::builder()
        .uri("/health")
        .body(Body::empty())
        .expect("request");
    let response = router(state()).oneshot(req).await.expect("responds");
    // tower-http emits `allow-origin: *` unconditionally, so the header is
    // present even with no Origin. Harmless — a same-origin client ignores
    // CORS headers entirely — and asserting its absence would pin us to a
    // dependency's internals rather than to our behaviour. What matters is
    // that adding the layer did not disturb an ordinary request.
    assert_eq!(response.status(), StatusCode::OK);
    let body = response.into_body();
    let bytes = axum::body::to_bytes(body, 64 * 1024)
        .await
        .expect("health body");
    let health: serde_json::Value = serde_json::from_slice(&bytes).expect("health is JSON");
    assert_eq!(health["service"], "utmelab-api");
    assert!(
        health["bank_version"]
            .as_str()
            .is_some_and(|v| !v.is_empty()),
        "health must still carry the content fingerprint (D42)"
    );
}
