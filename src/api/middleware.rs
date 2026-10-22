//! Public HTTP surface middleware. HTTP-only wrappers live here: ETag
//! generation today, plus the IP ceiling over the keyless discovery routes.
//! Nothing here knows business logic.

use axum::{
    body::{to_bytes, Body},
    extract::{ConnectInfo, State},
    http::{Request, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
};
use sha2::Digest;
use std::net::SocketAddr;

use crate::{auth::session, error::AppError, state::AppState};

/// Per-IP ceiling for the discovery routes, which have no key to meter. The
/// caller's address is the only identity available on that surface, and it
/// comes from [`session::client_ip`], the single reading every surface shares:
/// the entry the proxy attested, never one the caller supplied.
///
/// A request with no `ConnectInfo` (a service built without it) falls back to
/// loopback and shares one bucket. That is honest for a test and impossible in
/// production, where the binary always serves with connect info.
pub async fn public_limit(
    State(state): State<AppState>,
    request: Request<Body>,
    next: Next,
) -> Result<Response, AppError> {
    let direct = request
        .extensions()
        .get::<ConnectInfo<SocketAddr>>()
        .map(|c| c.0)
        .unwrap_or_else(|| SocketAddr::from(([127, 0, 0, 1], 0)));
    let ip = session::client_ip(request.headers(), direct);
    if !state.limiter.check_public(&ip).await {
        return Err(AppError::RateLimited);
    }
    Ok(next.run(request).await)
}

/// The discovery surface's freshness window, as a header value. It changes
/// only when the bank does, so a visitor's browser can answer from its own
/// copy instead of asking again; five minutes is short enough that a subject
/// added this morning is never stale for long. This is also what keeps the
/// keyless surface from absorbing a page view per visitor: a funnel page
/// costs one request per visit, not one per render.
pub const PUBLIC_CACHE_CONTROL: &str = "public, max-age=300";

/// Attach that window to whatever the inner layers produced. It runs outside
/// the ETag layer on purpose, so a `304` carries the directive too: the
/// revalidation already cost a read, and re-sending the header is what lets
/// the browser extend the copy it already holds.
pub async fn public_cache(request: Request<Body>, next: Next) -> Response {
    let mut response = next.run(request).await;
    if response.status().is_success() || response.status() == StatusCode::NOT_MODIFIED {
        response.headers_mut().insert(
            axum::http::header::CACHE_CONTROL,
            axum::http::HeaderValue::from_static(PUBLIC_CACHE_CONTROL),
        );
    }
    response
}

/// Attach the passive x-bank-version header to every response so consumers
/// can detect bank updates without polling.
pub async fn bank_version(
    State(state): State<AppState>,
    request: Request<Body>,
    next: Next,
) -> Response {
    let version = state
        .bank_version
        .read()
        .map(|v| v.clone())
        .unwrap_or_else(|_| format!("v{}", crate::store::schema::CONTRACT_VERSION));
    let mut response = next.run(request).await;
    if let Ok(val) = axum::http::HeaderValue::from_str(&version) {
        response
            .headers_mut()
            .insert(axum::http::HeaderName::from_static("x-bank-version"), val);
    }
    response
}

/// Strong ETag over exact response bytes for cacheable GETs. Matching
/// `If-None-Match` short-circuits to an empty 304. Bodies are already
/// capped by the 16KiB request limit plus our small responses; the 1MiB
/// collect cap below is a backstop, never a target.
pub async fn etag(request: Request<Body>, next: Next) -> Response {
    if request.method() != axum::http::Method::GET {
        return next.run(request).await;
    }
    let wanted = request
        .headers()
        .get(axum::http::header::IF_NONE_MATCH)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let response = next.run(request).await;
    if !response.status().is_success() {
        return response;
    }
    let (mut parts, body) = response.into_parts();
    let bytes = match to_bytes(body, 1024 * 1024).await {
        Ok(b) => b,
        Err(_) => return (StatusCode::BAD_GATEWAY, "body unreadable").into_response(),
    };
    let hex = crate::core::hex::encode(&sha2::Sha256::digest(&bytes));
    let tag = format!("\"{hex}\"");
    if etag_matches(&wanted, &tag) {
        parts.status = StatusCode::NOT_MODIFIED;
        parts.headers.remove(axum::http::header::CONTENT_LENGTH);
        parts.headers.remove(axum::http::header::CONTENT_TYPE);
        let mut res = Response::from_parts(parts, Body::empty());
        res.headers_mut().insert(
            axum::http::header::ETAG,
            tag.parse()
                .unwrap_or(axum::http::HeaderValue::from_static("\"unparseable\"")),
        );
        return res;
    }
    parts.headers.insert(
        axum::http::header::ETAG,
        tag.parse()
            .unwrap_or(axum::http::HeaderValue::from_static("\"unparseable\"")),
    );
    Response::from_parts(parts, Body::from(bytes))
}

fn etag_matches(header: &str, tag: &str) -> bool {
    header.split(',').any(|t| {
        let t = t.trim();
        t == "*" || t == tag || t.strip_prefix("W/").is_some_and(|w| w == tag)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_strong_weak_and_star() {
        assert!(etag_matches("\"abc\"", "\"abc\""));
        assert!(etag_matches("W/\"abc\"", "\"abc\""));
        assert!(etag_matches("*", "\"abc\""));
        assert!(etag_matches("\"x\", \"abc\"", "\"abc\""));
        assert!(!etag_matches("\"xyz\"", "\"abc\""));
        assert!(!etag_matches("", "\"abc\""));
    }
}
