//! Session-cookie identity for `internal`. Login verifies an argon2
//! password hash; the cookie carries a random token whose sha256 is stored
//! with an expiry. Passwords and tokens never rest in plaintext.
//!
//! Two audiences: customers (`SessionUser`) and admin (`AdminUser`).
//! Admin-only routes take `AdminUser`; the role travels from the
//! `dashboard_users` row, never from the client.

use axum::{
    extract::{FromRef, FromRequestParts},
    http::request::Parts,
};

use crate::{
    error::AppError,
    state::{AppState, DbState},
    store,
};

pub const SESSION_COOKIE: &str = "sid";
const SESSION_TTL_SECS: i64 = 12 * 3600;

pub fn cookie_token(headers: &axum::http::HeaderMap) -> Option<String> {
    let all = headers.get_all(axum::http::header::COOKIE);
    for v in all {
        let s = v.to_str().ok()?;
        for part in s.split(';') {
            let part = part.trim();
            if let Some(tok) = part.strip_prefix(&format!("{SESSION_COOKIE}=")) {
                return Some(tok.to_string());
            }
        }
    }
    None
}

/// Effective caller IP. Behind a proxy `ConnectInfo` is the proxy, so the
/// leftmost `X-Forwarded-For` entry wins when the proxy appends truthfully
/// (Caddy does); direct connections fall back to the socket address.
pub fn client_ip(headers: &axum::http::HeaderMap, direct: std::net::SocketAddr) -> String {
    headers
        .get("x-forwarded-for")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.split(',').next())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| direct.ip().to_string())
}

async fn identity(parts: &mut Parts, state: &AppState) -> Result<(String, String), AppError> {
    let tok = cookie_token(&parts.headers).ok_or(AppError::Unauthorized)?;
    let s = DbState::from_ref(state);
    store::accounts::verify_session(&s, &tok).await
}

/// Any logged-in dashboard user (customer or admin). Suspended or
/// unknown roles fail closed here, so every customer route inherits it.
pub struct SessionUser(pub String);

impl FromRequestParts<AppState> for SessionUser {
    type Rejection = AppError;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let (username, role) = identity(parts, state).await?;
        match role.as_str() {
            "customer" | "admin" => Ok(SessionUser(username)),
            _ => Err(AppError::Unauthorized),
        }
    }
}

/// Admin only. Customer sessions get 403, not a different login page.
pub struct AdminUser(pub String);

impl FromRequestParts<AppState> for AdminUser {
    type Rejection = AppError;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let (username, role) = identity(parts, state).await?;
        if role == "admin" {
            Ok(AdminUser(username))
        } else {
            Err(AppError::Forbidden)
        }
    }
}

pub fn session_cookie_value(token: &str, secure: bool) -> String {
    format!(
        "{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax{}",
        if secure { "; Secure" } else { "" }
    )
}

pub fn expired_cookie() -> String {
    format!("{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
}

pub fn now_unix() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

pub fn session_expiry() -> i64 {
    now_unix() + SESSION_TTL_SECS
}
