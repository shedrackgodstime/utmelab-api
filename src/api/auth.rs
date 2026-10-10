//! API-key authentication for the public API (D26, D27).
//!
//! One key type. The API never asks where it lives — a server, an app, or a
//! `curl` command are equally valid and the answer changes nothing.
//!
//! Failed authentication gives one identical response for unknown, malformed and
//! revoked keys. Distinguishing them would let a caller enumerate valid ids.

use axum::extract::FromRequestParts;
use axum::http::request::Parts;

use crate::AppState;
use crate::error::ApiError;
use crate::keys::ApiKey;

pub const HEADER: &str = "x-api-key";

/// The authenticated caller. Any handler that takes one is authenticated.
#[derive(Clone, Debug)]
pub struct Caller(pub ApiKey);

impl FromRequestParts<AppState> for Caller {
    type Rejection = ApiError;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let presented = parts
            .headers
            .get(HEADER)
            .and_then(|v| v.to_str().ok())
            .map(str::trim)
            .filter(|v| !v.is_empty())
            .ok_or(ApiError::Unauthorized)?;

        let key = state
            .keys
            .resolve(presented)
            .ok_or(ApiError::Unauthorized)?;

        // Every authenticated request spends a token (D27). A shared budget per
        // key — not per IP — so one busy integrator cannot exhaust another's.
        let allowed = state
            .limiter
            .lock()
            .map_err(|_| ApiError::internal("rate limiter poisoned"))?
            .check(&key.id, key.rate_limit);
        if !allowed {
            return Err(ApiError::rate_limited(key.rate_limit));
        }

        Ok(Caller(key))
    }
}
