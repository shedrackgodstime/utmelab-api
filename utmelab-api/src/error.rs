//! Shared consumer-facing error. Every handler in every surface returns
//! this; the mapping to status codes is the consumer contract and is
//! covered by unit tests below.

use axum::{http::StatusCode, response::IntoResponse, Json};
use serde::Serialize;

#[derive(Debug)]
pub enum AppError {
    BadRequest(String),
    Unauthorized,
    Forbidden,
    NotFound,
    Conflict(String),
    RateLimited,
    DbSaturated,
    DbUnavailable(&'static str),
    Upstream(String),
    Internal(String),
}

/// The consumer-facing body. `error` stays the human sentence (a client that
/// only reads it keeps working); `code` is the stable machine handle.
#[derive(Serialize)]
struct ErrorBody<'a> {
    error: &'a str,
    code: &'a str,
}

impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AppError::BadRequest(e) | AppError::Upstream(e) | AppError::Internal(e) => {
                write!(f, "{e}")
            }
            AppError::Conflict(e) => write!(f, "{e}"),
            AppError::Unauthorized => write!(f, "unauthorized"),
            AppError::Forbidden => write!(f, "scope denied"),
            AppError::RateLimited => write!(f, "slow down"),
            AppError::NotFound => write!(f, "not found"),
            AppError::DbSaturated => write!(f, "db saturated, retry"),
            AppError::DbUnavailable(w) => write!(f, "no {w} db configured"),
        }
    }
}

impl std::error::Error for AppError {}

impl AppError {
    /// Stable machine handle; does not change when a message is reworded.
    fn code(&self) -> &'static str {
        match self {
            AppError::BadRequest(_) => "bad_request",
            AppError::Unauthorized => "unauthorized",
            AppError::Forbidden => "forbidden",
            AppError::NotFound => "not_found",
            AppError::Conflict(_) => "conflict",
            AppError::RateLimited => "rate_limited",
            AppError::DbSaturated => "db_saturated",
            AppError::DbUnavailable(_) => "db_unavailable",
            AppError::Upstream(_) => "upstream_error",
            AppError::Internal(_) => "internal_error",
        }
    }

    /// What the client may read. A client mistake keeps its detail; engine,
    /// database, and internal text is never surfaced (it is logged instead),
    /// so a SQL string or connection error cannot leak through a 5xx.
    fn public_detail(&self) -> String {
        match self {
            AppError::BadRequest(e) => e.clone(),
            AppError::Conflict(e) => e.clone(),
            AppError::Unauthorized => "missing or invalid credentials".to_string(),
            AppError::Forbidden => "scope denied".to_string(),
            AppError::NotFound => "not found".to_string(),
            AppError::RateLimited => "slow down".to_string(),
            AppError::DbSaturated => "database busy, retry shortly".to_string(),
            AppError::DbUnavailable(_) => "database unavailable".to_string(),
            AppError::Upstream(_) | AppError::Internal(_) => {
                "the server could not complete the request".to_string()
            }
        }
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> axum::response::Response {
        let status = match &self {
            AppError::BadRequest(_) => StatusCode::BAD_REQUEST,
            AppError::Unauthorized => StatusCode::UNAUTHORIZED,
            AppError::Forbidden => StatusCode::FORBIDDEN,
            AppError::RateLimited => StatusCode::TOO_MANY_REQUESTS,
            AppError::NotFound => StatusCode::NOT_FOUND,
            AppError::Conflict(_) => StatusCode::CONFLICT,
            AppError::DbSaturated | AppError::DbUnavailable(_) => StatusCode::SERVICE_UNAVAILABLE,
            AppError::Upstream(_) => StatusCode::BAD_GATEWAY,
            AppError::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
        };
        // Operators get the real cause; clients get the safe sentence below.
        match &self {
            AppError::Internal(e) | AppError::Upstream(e) => {
                tracing::error!(code = self.code(), error = %e, "request failed");
            }
            AppError::DbUnavailable(what) => {
                tracing::warn!(code = self.code(), db = what, "request failed");
            }
            _ => {}
        }
        let detail = self.public_detail();
        let mut res = (
            status,
            Json(ErrorBody {
                error: &detail,
                code: self.code(),
            }),
        )
            .into_response();
        if matches!(self, AppError::RateLimited) {
            res.headers_mut().insert(
                axum::http::header::RETRY_AFTER,
                axum::http::HeaderValue::from_static("60"),
            );
        }
        res
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn status_of(e: AppError) -> StatusCode {
        e.into_response().status()
    }

    #[test]
    fn error_status_contract() {
        assert_eq!(
            status_of(AppError::BadRequest("x".into())),
            StatusCode::BAD_REQUEST
        );
        assert_eq!(status_of(AppError::Unauthorized), StatusCode::UNAUTHORIZED);
        assert_eq!(status_of(AppError::Forbidden), StatusCode::FORBIDDEN);
        assert_eq!(
            status_of(AppError::RateLimited),
            StatusCode::TOO_MANY_REQUESTS
        );
        assert_eq!(status_of(AppError::NotFound), StatusCode::NOT_FOUND);
        assert_eq!(
            status_of(AppError::Conflict("short on x".into())),
            StatusCode::CONFLICT
        );
        assert_eq!(
            status_of(AppError::DbSaturated),
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            status_of(AppError::DbUnavailable("sync")),
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            status_of(AppError::Upstream("x".into())),
            StatusCode::BAD_GATEWAY
        );
        assert_eq!(
            status_of(AppError::Internal("x".into())),
            StatusCode::INTERNAL_SERVER_ERROR
        );
    }

    async fn body_of(e: AppError) -> String {
        let res = e.into_response();
        let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
            .await
            .expect("body");
        String::from_utf8(bytes.to_vec()).expect("utf8")
    }

    #[tokio::test]
    async fn internal_causes_are_logged_not_leaked() {
        let body = body_of(AppError::Upstream("no such table: secrets".into())).await;
        assert!(!body.contains("secrets"), "engine text leaked: {body}");
        assert!(body.contains("upstream_error"), "{body}");
    }

    #[tokio::test]
    async fn client_mistakes_keep_their_detail() {
        let body = body_of(AppError::BadRequest("bad target_type".into())).await;
        assert!(body.contains("bad target_type"), "{body}");
        assert!(body.contains("bad_request"), "{body}");
    }

    #[tokio::test]
    async fn a_conflict_names_the_gap_and_is_not_hidden() {
        let body = body_of(AppError::Conflict(
            "Only 1/3 topics ready; short on: sets (need 2, have 1)".into(),
        ))
        .await;
        assert!(body.contains("need 2, have 1"), "{body}");
        assert!(body.contains("conflict"), "{body}");
    }
}
