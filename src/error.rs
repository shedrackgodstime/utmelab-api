//! Error type and its RFC 9457 Problem Details wire shape (D25).
//!
//! Every failure that reaches a client goes through here, so the error shape is
//! the same everywhere: `type`, `title`, `status`, `detail`, plus a stable
//! machine-readable `code`.

use axum::Json;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::Serialize;

#[derive(Debug, thiserror::Error)]
pub enum ApiError {
    #[error("configuration error: {0}")]
    Config(String),

    #[error("{code}: {detail}")]
    NotFound {
        /// Stable, machine-readable. Becomes `code` and the `type` slug.
        code: &'static str,
        detail: String,
    },

    #[error("missing or invalid credentials")]
    Unauthorized,

    #[error("{code}: {detail}")]
    BadRequest { code: &'static str, detail: String },

    #[error("rate limit exceeded")]
    RateLimited {
        /// The key's configured allowance, echoed so a client can adapt.
        per_minute: u32,
    },

    #[error("daily limit exceeded: {reason}")]
    DailyLimited {
        /// Why, in the consumer's words — the cap exists to protect the bank,
        /// not to punish them.
        reason: &'static str,
    },

    #[error("internal error: {0}")]
    Internal(String),
}

impl ApiError {
    /// What a client is told to wait for a daily cap. Reports reset at UTC
    /// midnight; an hour is the conservative honest answer for "come back
    /// later", and no client is harmed by waiting an hour too long.
    const DAILY_LIMIT_RETRY_AFTER: u64 = 3600;

    pub fn config(msg: impl Into<String>) -> Self {
        Self::Config(msg.into())
    }

    pub fn internal(msg: impl Into<String>) -> Self {
        Self::Internal(msg.into())
    }

    pub fn rate_limited(per_minute: u32) -> Self {
        Self::RateLimited { per_minute }
    }

    /// The daily report cap: same status, a different honest `Retry-After`
    /// (D43) so a client does not retry every second against a limit that
    /// resets in hours.
    pub fn daily_limit(reason: &'static str) -> Self {
        Self::DailyLimited { reason }
    }

    pub fn bad_request(code: &'static str, detail: impl Into<String>) -> Self {
        Self::BadRequest {
            code,
            detail: detail.into(),
        }
    }

    pub fn not_found(code: &'static str, detail: impl Into<String>) -> Self {
        Self::NotFound {
            code,
            detail: detail.into(),
        }
    }

    fn status(&self) -> StatusCode {
        match self {
            Self::BadRequest { .. } => StatusCode::BAD_REQUEST,
            Self::NotFound { .. } => StatusCode::NOT_FOUND,
            Self::Unauthorized => StatusCode::UNAUTHORIZED,
            Self::RateLimited { .. } | Self::DailyLimited { .. } => StatusCode::TOO_MANY_REQUESTS,

            Self::Config(_) | Self::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }

    fn code(&self) -> &'static str {
        match self {
            Self::Config(_) => "configuration_error",
            Self::BadRequest { code, .. } => code,
            Self::NotFound { code, .. } => code,
            Self::Unauthorized => "unauthorized",
            Self::RateLimited { .. } => "rate_limited",
            Self::DailyLimited { .. } => "daily_limit_exceeded",
            Self::Internal(_) => "internal_error",
        }
    }

    fn title(&self) -> &'static str {
        match self {
            Self::Config(_) => "Server configuration error",
            Self::BadRequest { .. } => "Bad request",
            Self::NotFound { .. } => "Not found",
            Self::Unauthorized => "Missing or invalid API key",
            Self::RateLimited { .. } => "Rate limit exceeded",
            Self::DailyLimited { .. } => "Daily limit exceeded",
            Self::Internal(_) => "Internal server error",
        }
    }

    /// What the client is allowed to read.
    fn public_detail(&self) -> String {
        match self {
            Self::BadRequest { detail, .. } => detail.clone(),
            Self::NotFound { detail, .. } => detail.clone(),
            Self::Unauthorized => "Provide a valid key in the X-API-Key header.".to_owned(),
            Self::RateLimited { per_minute } => {
                format!("This key is limited to {per_minute} requests per minute.")
            }
            Self::DailyLimited { reason } => (*reason).to_owned(),
            // Never surface configuration, database, or internal messages.
            _ => "The server could not complete the request.".to_owned(),
        }
    }
}

/// A client-safe view of the error. Internal causes are logged, never returned —
/// a stack trace or a SQL string in a response body is a leak.
#[derive(Serialize)]
pub struct Problem {
    #[serde(rename = "type")]
    pub kind: String,
    pub title: &'static str,
    pub status: u16,
    pub detail: String,
    pub code: &'static str,
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let status = self.status();
        if status.is_server_error() {
            tracing::error!(error = %self, "request failed");
        }

        let detail = self.public_detail();

        let problem = Problem {
            kind: format!("https://docs.utmelab.com/errors/{}", self.code()),
            title: self.title(),
            status: status.as_u16(),
            detail,
            code: self.code(),
        };
        // Honouring `Retry-After` is the whole point of sending 429: a client
        // that knows when to come back does not have to guess or spin (D43).
        let mut response = (status, Json(problem)).into_response();
        if let Some(seconds) = self.retry_after_secs() {
            if let Ok(value) = seconds.to_string().parse() {
                response.headers_mut().insert("retry-after", value);
            }
        }
        response
    }
}

impl ApiError {
    /// Seconds until this key may retry. `None` for everything but the two
    /// limit errors — a 404 or a 500 must never carry a `Retry-After`.
    fn retry_after_secs(&self) -> Option<u64> {
        match self {
            // The bucket refills continuously at `rate_limit` per minute, so
            // one token is never more than 60s away.
            Self::RateLimited { per_minute } if *per_minute > 0 => Some(60),
            Self::DailyLimited { .. } => Some(Self::DAILY_LIMIT_RETRY_AFTER),
            _ => None,
        }
    }
}

#[cfg(test)]
mod retry_after_tests {
    use super::*;
    use axum::body::Body;
    use axum::http::header::RETRY_AFTER;

    fn header_of(err: ApiError) -> Option<String> {
        err.into_response()
            .headers()
            .get(RETRY_AFTER)
            .and_then(|v| v.to_str().ok())
            .map(str::to_owned)
    }

    #[test]
    fn a_rate_limited_key_is_told_when_to_come_back() {
        assert_eq!(header_of(ApiError::rate_limited(30)), Some("60".into()));
    }

    #[test]
    fn a_daily_cap_asks_for_much_more_patience_than_a_minute() {
        let err = ApiError::daily_limit("Ten reports a day.");
        let secs: u64 = header_of(err)
            .expect("daily limits carry Retry-After")
            .parse()
            .unwrap();
        assert!(
            secs >= 3600,
            "retrying in 60s against a daily cap is the spin we are removing"
        );
    }

    #[test]
    fn errors_that_are_not_limits_never_carry_retry_after() {
        for err in [
            ApiError::not_found("nope", "gone"),
            ApiError::bad_request("bad", "no"),
            ApiError::Unauthorized,
            ApiError::internal("db down"),
        ] {
            assert_eq!(header_of(err), None, "only 429s may say when to retry");
        }
    }

    #[test]
    fn an_unlimited_key_is_not_rate_limited_by_its_own_zero() {
        // rate_limit 0 means "always denied", and must still be retryable
        // rather than producing a header we cannot honestly compute.
        assert_eq!(header_of(ApiError::rate_limited(0)), None);
    }

    #[test]
    fn both_limit_kinds_share_the_429_status() {
        for err in [ApiError::rate_limited(30), ApiError::daily_limit("x")] {
            let response = err.into_response();
            assert_eq!(response.status(), StatusCode::TOO_MANY_REQUESTS);
            let _ = Body::new(response.into_body());
        }
    }
}
