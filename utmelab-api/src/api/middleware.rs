//! Public HTTP surface middleware. HTTP-only wrappers live here:
//! ETag generation today; CORS-adjacent and rate-limit headers join when
//! they land. Nothing here knows business logic.

use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
};
use sha2::Digest;

/// Strong ETag over exact response bytes for cacheable GETs. Matching
/// `If-None-Match` short-circuits to an empty 304. Bodies are already
/// capped by the 64KiB request limit plus our small responses; the 1MiB
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
