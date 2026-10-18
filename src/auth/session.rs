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

/// Effective caller address, for rate limiting and audit.
///
/// The whole of the security here is trust order:
///
/// 1. The socket peer is unforgeable, but the binary binds loopback (see
///    [`crate::config::BIND_HOST`]), so on its own it only ever names our own
///    proxy.
/// 2. The proxy writes the address it observed (Caddy replaces an incoming
///    value; a proxy that appends puts its own last), so the **last**
///    `X-Forwarded-For` entry is the one hop we can attest.
/// 3. Everything before it was supplied by the caller. Reading the first
///    entry, as this once did, let any caller choose their own bucket by
///    rotating a header, which defeated every ceiling keyed on this.
///
/// A value that does not parse as an address falls back to the socket, which
/// for a loopback-only binary puts every such caller in one shared bucket.
/// That is deliberate: an unidentifiable caller is limited collectively,
/// never unlimited.
pub fn client_ip(headers: &axum::http::HeaderMap, direct: std::net::SocketAddr) -> String {
    let attested = headers
        .get("x-forwarded-for")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| {
            value
                .rsplit(',')
                .map(str::trim)
                .find(|part| !part.is_empty())
        })
        .and_then(parse_addr);
    attested
        .map(|ip| ip.to_string())
        .unwrap_or_else(|| direct.ip().to_string())
}

/// The address in one forwarded entry, which may be bare or carry a port
/// (`host`, `host:port`, `[v6]`, `[v6]:port`). A proxy that includes the port
/// must not turn one caller into one bucket per connection.
fn parse_addr(entry: &str) -> Option<std::net::IpAddr> {
    let host = entry
        .strip_prefix('[')
        .and_then(|rest| rest.split(']').next())
        .unwrap_or(entry);
    host.parse().ok().or_else(|| {
        host.rsplit_once(':')
            .and_then(|(host, _)| host.parse().ok())
    })
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

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderMap;

    fn socket() -> std::net::SocketAddr {
        "127.0.0.1:5555".parse().expect("a socket address")
    }

    fn forwarded(value: &str) -> String {
        let mut headers = HeaderMap::new();
        headers.insert("x-forwarded-for", value.parse().expect("a header value"));
        client_ip(&headers, socket())
    }

    /// The entry our own proxy appended is the identity; anything before it is
    /// a claim. This is the test that a rotating header cannot buy a fresh
    /// bucket, which is what the ceiling looked like before.
    #[test]
    fn the_last_forwarded_entry_wins_over_a_claimed_one() {
        assert_eq!(forwarded("203.0.113.9, 198.51.100.7"), "198.51.100.7");
        assert_eq!(forwarded("203.0.113.9,198.51.100.7"), "198.51.100.7");
    }

    #[test]
    fn one_entry_is_used_as_it_stands() {
        assert_eq!(forwarded("198.51.100.7"), "198.51.100.7");
        assert_eq!(forwarded(" [2001:db8::1] "), "2001:db8::1");
    }

    /// A port must not make one caller into one bucket per connection.
    #[test]
    fn a_port_is_dropped() {
        assert_eq!(forwarded("198.51.100.7:41234"), "198.51.100.7");
        assert_eq!(forwarded("[2001:db8::1]:443"), "2001:db8::1");
    }

    #[test]
    fn surrounding_whitespace_does_not_hide_the_entry() {
        assert_eq!(forwarded("203.0.113.9 , 198.51.100.7 ,"), "198.51.100.7");
    }

    /// Fail closed: an unusable value limits the caller collectively rather
    /// than exempting them.
    #[test]
    fn an_unusable_value_falls_back_to_the_socket() {
        for value in ["", " , ", "not-an-address", "localhost"] {
            assert_eq!(forwarded(value), "127.0.0.1", "value {value:?}");
        }
        assert_eq!(client_ip(&HeaderMap::new(), socket()), "127.0.0.1");
    }
}
