//! `POST /api/v1/questions/{id}/report` — flag a broken question.
//!
//! The objective, stated once: turn consumer-side flags into an aggregated
//! review queue for us, without creating a spam vector, a moderation burden,
//! or write-path complexity. Five constraints enforce that (see `reports/store.rs`).
//!
//! Requires a key like every other write. Subject to the key's per-minute limit
//! **and** a tight daily report cap — reporting is rare, so the cap is generous
//! for humans and useless for floods.

use axum::Json;
use axum::Router;
use axum::extract::{Path, State};
use axum::response::IntoResponse;
use axum::routing::post;
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

use crate::AppState;
use crate::api::auth::Caller;
use crate::error::ApiError;
use crate::reports::{DEFAULT_REPORTS_PER_DAY, ReportReason};

#[derive(Deserialize, ToSchema)]
pub struct ReportBody {
    /// One of: wrong_answer, unclear_stem, broken_option, wrong_explanation, other.
    pub reason: String,
    /// Optional context, max 500 characters. No PII — never send names or emails.
    pub detail: Option<String>,
}

#[derive(Serialize, ToSchema)]
pub struct ReportReceipt {
    pub id: String,
    pub question_id: String,
    pub reason: String,
    /// True when this exact flag was already filed — POST is idempotent here.
    pub duplicate: bool,
}

pub fn router() -> Router<AppState> {
    Router::new().route("/v1/questions/{id}/report", post(report))
}

#[utoipa::path(
    post,
    path = "/api/v1/questions/{id}/report",
    tag = "questions",
    operation_id = "reportQuestion",
    description = "Flag a broken question. Reasons are a closed set so reports aggregate; \
free-text detail is optional and capped. Reports never change the bank — they join a \
review queue, and a question with many flags gets human eyes.",
    params(("id" = String, Path, description = "Question id.")),
    responses(
        (status = 201, body = ReportReceipt),
        (status = 400, description = "Unknown reason, or detail over 500 characters"),
        (status = 401, description = "Missing or invalid API key"),
        (status = 404, description = "No such question"),
        (status = 429, description = "Over a limit — per-minute or the daily report cap"),
    ),
    security(("ApiKeyAuth" = [])),
)]
pub async fn report(
    State(state): State<AppState>,
    Caller(key): Caller,
    Path(id): Path<String>,
    Json(body): Json<ReportBody>,
) -> Result<axum::response::Response<axum::body::Body>, ApiError> {
    // The question must exist — but a missing id is a 404 like any other, not a
    // special case. Question ids are public content.
    if state.bank.question(&id).is_none() {
        return Err(ApiError::not_found(
            "question_not_found",
            format!("No question with id '{id}'."),
        ));
    }

    let reason = ReportReason::parse(body.reason.trim()).ok_or_else(|| {
        ApiError::bad_request(
            "unknown_reason",
            "reason must be one of: wrong_answer, unclear_stem, broken_option, wrong_explanation, other.",
        )
    })?;

    // Daily cap, checked before filing. Separate from the per-minute bucket:
    // reporting is rare enough that ten a day is generous. The tokio mutex
    // cannot be poisoned, so there is no lock-failure branch to map (R3).
    let mut reports = state.reports.lock().await;
    if reports.recent_count(&key.id) >= DEFAULT_REPORTS_PER_DAY as usize {
        return Err(ApiError::daily_limit(
            "This key has filed its reports for today; the cap resets at midnight UTC.",
        ));
    }

    let (record, duplicate) = reports.file(&key.id, &id, reason, body.detail)?;

    // 201 for a new flag, 200 for a duplicate — the client can tell whether
    // anything happened without a second call.
    let status = if duplicate {
        axum::http::StatusCode::OK
    } else {
        axum::http::StatusCode::CREATED
    };
    Ok((
        status,
        Json(ReportReceipt {
            id: record.id,
            question_id: record.question_id,
            reason: reason.as_str().to_owned(),
            duplicate,
        }),
    )
        .into_response())
}
