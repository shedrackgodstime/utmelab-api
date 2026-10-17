//! Consumer flags. One endpoint serves every reportable kind — a
//! question, a topic, a passage, a novel — dispatching on the target
//! type rather than growing a route per kind. The original
//! `POST /v1/questions/{id}/report` stays as a thin delegate so existing
//! callers keep working.
//!
//! Every filing is key-gated, subject to the key's per-minute limit and
//! a tight daily cap (see `core::reports`): reporting is rare, so the cap
//! is generous for humans and useless for floods.

use axum::{
    extract::{Path, State},
    http::StatusCode,
    routing::post,
    Json, Router,
};
use serde::Deserialize;

use crate::{
    auth::{api_key::AuthedKey, Auth, SCOPE_WRITE_REPORTS},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

#[derive(Deserialize)]
pub struct ReportBody {
    /// One of: question, topic, passage, novel.
    pub target_type: String,
    /// The target's id. Topics have no single id, so theirs is the
    /// slash-joined `exam/subject/slug`.
    pub target_id: String,
    /// One of: wrong_answer, unclear_stem, broken_option,
    /// wrong_explanation, other.
    pub reason: String,
    /// Optional context, max 500 characters. No PII.
    pub detail: Option<String>,
}

#[derive(Deserialize)]
pub struct QuestionReportBody {
    pub reason: String,
    pub detail: Option<String>,
}

/// `POST /v1/report` — the general entry point.
pub async fn file(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Json(b): Json<ReportBody>,
) -> Result<(StatusCode, Json<core::models::ReportFiled>), AppError> {
    report(s, auth, b.target_type, b.target_id, b.reason, b.detail).await
}

/// `POST /v1/questions/{id}/report` — kept for URL compatibility; the
/// id is the target id, the kind is fixed to `question`.
pub async fn report_question(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
    Json(b): Json<QuestionReportBody>,
) -> Result<(StatusCode, Json<core::models::ReportFiled>), AppError> {
    report(s, auth, "question".to_string(), id, b.reason, b.detail).await
}

/// The one filing path both routes share.
async fn report(
    s: DbState,
    auth: Auth,
    target_type: String,
    target_id: String,
    reason: String,
    detail: Option<String>,
) -> Result<(StatusCode, Json<core::models::ReportFiled>), AppError> {
    auth.require(SCOPE_WRITE_REPORTS)?;
    if !s
        .limiter
        .check(
            &format!("report:{}", auth.key_id),
            core::reports::MAX_REPORTS_PER_MINUTE,
            std::time::Duration::from_secs(60),
        )
        .await
    {
        return Err(AppError::RateLimited);
    }
    let target_type = core::reports::parse_target_type(target_type.trim())?;
    let target_id = target_id.trim().to_string();
    if target_id.is_empty() {
        return Err(AppError::BadRequest("target_id required".to_string()));
    }
    let reason = core::reports::parse_reason(reason.trim())?;
    if let Some(d) = &detail {
        if d.chars().count() > core::reports::MAX_DETAIL_CHARS {
            return Err(AppError::BadRequest(
                "detail over 500 characters".to_string(),
            ));
        }
    }
    if !store::catalog::target_exists(&s, target_type, &target_id).await? {
        return Err(AppError::NotFound);
    }
    let (rid, duplicate) = store::accounts::file_report(
        &s,
        &auth.key_id,
        target_type,
        &target_id,
        reason,
        detail.as_deref(),
    )
    .await?;
    let status = if duplicate {
        StatusCode::OK
    } else {
        StatusCode::CREATED
    };
    Ok((
        status,
        Json(core::models::ReportFiled {
            id: rid,
            target_type: target_type.to_string(),
            target_id,
            reason: reason.to_string(),
            duplicate,
        }),
    ))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/report", post(file))
        .route("/v1/questions/{id}/report", post(report_question))
        .with_state(state)
}
