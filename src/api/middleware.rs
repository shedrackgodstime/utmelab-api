//! Response headers that make the API integrable: rate-limit introspection
//! (R6) and HTTP caching (R9).
//!
//! One middleware, two jobs:
//!
//! **ETag / 304.** Every `GET` under `/api/v1` (except the per-key probe
//! `/keys/me`) carries `ETag: "<bank_version>-<uri hash>"` and honours
//! `If-None-Match` with a `304` — a consumer polls `bank_version` through the
//! cache layer instead of re-downloading the catalog. A 304 skips the token
//! spend, which is correct: nothing was served.
//!
//! **`X-RateLimit-*`.** After the handler ran (the `Caller` extractor already
//! spent the token), the remaining budget is reported on authenticated
//! responses — including 429s, so a client can adapt instead of backing off
//! blind. Peek-only: this never spends a second token.
//!
//! Excluded from both: `/health` (deliberately polled whole) and `/keys/me`
//! (per-key, not content-addressed).
use axum::extract::State;
use axum::http::{HeaderMap, HeaderName, HeaderValue, Method, StatusCode};
use axum::middleware::Next;
use axum::response::Response;
use sha2::{Digest, Sha256};

use crate::AppState;
use crate::api::auth::HEADER as API_KEY_HEADER;

pub async fn response_headers(
    State(state): State<AppState>,
    request: axum::extract::Request,
    next: Next,
) -> Response {
    let method = request.method().clone();
    let path = request.uri().path().to_owned();
    let query = request.uri().query().unwrap_or("").to_owned();
    let cacheable = is_cacheable(&method, &path);

    // Content fingerprint + URI = the etag. bank_version alone would 304 a
    // client whose filter changed; the URI pins it to the exact request.
    let etag = cacheable.then(|| {
        let hash =
            Sha256::digest(format!("{}\n{}?{}", state.bank.version(), path, query).as_bytes());
        let hex: String = hash.iter().take(8).map(|b| format!("{b:02x}")).collect();
        format!("\"{}-{hex}\"", state.bank.version())
    });

    if let Some(tag) = &etag {
        if let Some(client) = request
            .headers()
            .get(axum::http::header::IF_NONE_MATCH)
            .and_then(|v| v.to_str().ok())
            && client == tag
        {
            return not_modified(tag, cache_control_for(&path));
        }
    }

    // Read the key before dispatch: the extractor consumes the request.
    let presented = request
        .headers()
        .get(API_KEY_HEADER)
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .map(str::to_owned);

    let mut response = next.run(request).await;

    if let Some(tag) = etag {
        append(response.headers_mut(), "etag", &tag);
        append(
            response.headers_mut(),
            "cache-control",
            cache_control_for(&path),
        );
    }

    // Only authenticated responses carry budget headers. The resolve is the
    // cached path (Turso TTL / file reload), and peek never spends.
    if let Some(presented) = presented {
        if let Some(key) = state.keys.resolve(&presented).await {
            let (limit, remaining, reset) = match state.limiter.lock() {
                Ok(limiter) => limiter.peek(&key.id, key.rate_limit),
                Err(_) => return response,
            };
            let headers = response.headers_mut();
            append(headers, "x-ratelimit-limit", &limit.to_string());
            append(headers, "x-ratelimit-remaining", &remaining.to_string());
            append(headers, "x-ratelimit-reset", &reset.to_string());
        }
    }

    response
}

/// Catalog lives in RAM and changes on import; questions grow on merge. Both
/// are worth a minute's staleness; the catalog an hour's.
fn cache_control_for(path: &str) -> &'static str {
    if path.contains("/questions") {
        "public, max-age=60"
    } else {
        "public, max-age=3600"
    }
}

fn is_cacheable(method: &Method, path: &str) -> bool {
    method == Method::GET && path.starts_with("/api/v1") && path != "/api/v1/keys/me"
}

fn not_modified(tag: &str, cache_control: &'static str) -> Response {
    let mut response = Response::builder()
        .status(StatusCode::NOT_MODIFIED)
        .body(axum::body::Body::empty())
        .expect("304 response");
    let headers = response.headers_mut();
    append(headers, "etag", tag);
    append(headers, "cache-control", cache_control);
    response
}

fn append(headers: &mut HeaderMap, name: &'static str, value: &str) {
    if let Ok(value) = HeaderValue::from_str(value) {
        headers.insert(HeaderName::from_static(name), value);
    }
}
