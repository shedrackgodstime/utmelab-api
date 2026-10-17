//! Consumer flags. One endpoint serves every reportable kind — a
//! question, a topic, a passage, a novel — dispatching on the target
//! type rather than growing a route per kind.
//!
//! Every filing is key-gated, subject to the key's per-minute limit and
//! a tight daily cap (see `core::reports`): reporting is rare, so the cap
//! is generous for humans and useless for floods.

use axum::{extract::State, http::StatusCode, routing::post, Json, Router};
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
    /// Optional context, capped at [`crate::core::reports::MAX_DETAIL_CHARS`]
    /// characters. No PII.
    pub detail: Option<String>,
}

/// `POST /v1/report` — the single entry point. Dispatches on `target_type`.
pub async fn file(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Json(b): Json<ReportBody>,
) -> Result<(StatusCode, Json<core::models::ReportFiled>), AppError> {
    report(s, auth, b.target_type, b.target_id, b.reason, b.detail).await
}

/// The one filing path.
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
            return Err(AppError::BadRequest(format!(
                "detail over {} characters",
                core::reports::MAX_DETAIL_CHARS
            )));
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
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::testing::{api_schema, bank_schema, call, connect, issue_key, replica, state};
    use axum::http::StatusCode;

    /// Offline replica with a read key and a write key, seeded through a raw
    /// connection. The happy filing needs the store push (Turso), so this stops
    /// at the validation boundary: what it proves is the scope gate, not the
    /// write. The sweep in `routes` proves the same routes reject a missing key.
    async fn seeded_app() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["questions", "verifications"]).await;
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        issue_key(
            &conn,
            "reporter.secret",
            "commercial",
            "write:reports",
            false,
        )
        .await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    async fn post(app: axum::Router, key: Option<&str>, body: &str) -> StatusCode {
        call(app, "POST", "/api/v1/report", key, Some(body)).await.0
    }

    #[tokio::test]
    async fn filing_needs_the_write_scope() {
        let app = seeded_app().await;
        let ok = r#"{"target_type":"question","target_id":"q1","reason":"other"}"#;

        // A read key cannot file, however well-formed the body.
        assert_eq!(
            post(app.clone(), Some("reader.secret"), ok).await,
            StatusCode::FORBIDDEN
        );

        // The write key clears the scope gate; a bad kind is the client's
        // mistake (400), not a refusal.
        assert_eq!(
            post(
                app.clone(),
                Some("reporter.secret"),
                r#"{"target_type":"nope","target_id":"q1","reason":"other"}"#
            )
            .await,
            StatusCode::BAD_REQUEST
        );

        // A well-formed filing for a target we do not hold is 404, so the gate
        // let it through to the read.
        assert_eq!(
            post(app, Some("reporter.secret"), ok).await,
            StatusCode::NOT_FOUND
        );
    }
}
