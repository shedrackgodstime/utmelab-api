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
    RateLimited,
    DbSaturated,
    DbUnavailable(&'static str),
    Upstream(String),
    Internal(String),
}

#[derive(Serialize)]
struct ErrorBody<'a> {
    error: &'a str,
}

impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AppError::BadRequest(e) | AppError::Upstream(e) | AppError::Internal(e) => {
                write!(f, "{e}")
            }
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

impl IntoResponse for AppError {
    fn into_response(self) -> axum::response::Response {
        let status = match &self {
            AppError::BadRequest(_) => StatusCode::BAD_REQUEST,
            AppError::Unauthorized => StatusCode::UNAUTHORIZED,
            AppError::Forbidden => StatusCode::FORBIDDEN,
            AppError::RateLimited => StatusCode::TOO_MANY_REQUESTS,
            AppError::NotFound => StatusCode::NOT_FOUND,
            AppError::DbSaturated | AppError::DbUnavailable(_) => StatusCode::SERVICE_UNAVAILABLE,
            AppError::Upstream(_) => StatusCode::BAD_GATEWAY,
            AppError::Internal(_) => StatusCode::INTERNAL_SERVER_ERROR,
        };
        let mut res = (
            status,
            Json(ErrorBody {
                error: &self.to_string(),
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
}
