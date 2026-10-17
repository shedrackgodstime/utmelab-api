//! `x-api-key` extractor. One wire, one identity for `api` + `mcp`.
//! Verification SQL lives in `store::accounts`; this file only extracts
//! the header and returns the identity.

use axum::{
    extract::{FromRef, FromRequestParts},
    http::{header::HeaderName, request::Parts},
};

use crate::{
    auth::Auth,
    error::AppError,
    state::{AppState, DbState},
    store,
};

pub const KEY_HEADER: &str = "x-api-key";

/// Extractor: any handler taking this is key-gated. Callers then check
/// scopes in the handler via [`Auth::require`], one line per operation,
/// so neither surface can forget. Session-based surfaces use their own
/// extractors instead; the two identities never mix.
pub struct AuthedKey(pub Auth);

impl FromRequestParts<AppState> for AuthedKey {
    type Rejection = AppError;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let raw = parts
            .headers
            .get(HeaderName::from_static(KEY_HEADER))
            .and_then(|v| v.to_str().ok())
            .ok_or(AppError::Unauthorized)?;
        let s = DbState::from_ref(state);
        let auth = store::accounts::verify_key(&s, raw).await?;
        // Enforced here, not per handler: every keyed route on `api` and
        // `mcp` inherits the per-key ceiling by construction.
        if !s.limiter.check_api_key(&auth.key_id, auth.is_admin).await {
            return Err(AppError::RateLimited);
        }
        Ok(AuthedKey(auth))
    }
}
