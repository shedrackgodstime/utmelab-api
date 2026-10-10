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

    #[error("rate limit exceeded")]
    RateLimited {
        /// The key's configured allowance, echoed so a client can adapt.
        per_minute: u32,
    },

    #[error("internal error: {0}")]
    Internal(String),
}

impl ApiError {
    pub fn config(msg: impl Into<String>) -> Self {
        Self::Config(msg.into())
    }

    pub fn internal(msg: impl Into<String>) -> Self {
        Self::Internal(msg.into())
    }

    pub fn rate_limited(per_minute: u32) -> Self {
        Self::RateLimited { per_minute }
    }

    pub fn not_found(code: &'static str, detail: impl Into<String>) -> Self {
        Self::NotFound {
            code,
            detail: detail.into(),
        }
    }

    fn status(&self) -> StatusCode {
        match self {
            Self::NotFound { .. } => StatusCode::NOT_FOUND,
            Self::Unauthorized => StatusCode::UNAUTHORIZED,
            Self::RateLimited { .. } => StatusCode::TOO_MANY_REQUESTS,

            Self::Config(_) | Self::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }

    fn code(&self) -> &'static str {
        match self {
            Self::Config(_) => "configuration_error",
            Self::NotFound { code, .. } => code,
            Self::Unauthorized => "unauthorized",
            Self::RateLimited { .. } => "rate_limited",
            Self::Internal(_) => "internal_error",
        }
    }

    fn title(&self) -> &'static str {
        match self {
            Self::Config(_) => "Server configuration error",
            Self::NotFound { .. } => "Not found",
            Self::Unauthorized => "Missing or invalid API key",
            Self::RateLimited { .. } => "Rate limit exceeded",
            Self::Internal(_) => "Internal server error",
        }
    }

    /// What the client is allowed to read.
    fn public_detail(&self) -> String {
        match self {
            Self::NotFound { detail, .. } => detail.clone(),
            Self::Unauthorized => "Provide a valid key in the X-API-Key header.".to_owned(),
            Self::RateLimited { per_minute } => {
                format!("This key is limited to {per_minute} requests per minute.")
            }
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
        (status, Json(problem)).into_response()
    }
}
