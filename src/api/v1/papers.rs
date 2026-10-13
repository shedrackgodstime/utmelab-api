//! `GET /api/v1/exams/{exam}/papers` — how an exam is shaped.
//!
//! Read-only. This is the *scheme*: which subjects, how many questions each,
//! what the candidate must do. It is a constant restated from the bank (D19),
//! so it changes when the bank changes and is never stored twice.
//!
//! Everything it says about our readiness is honest: `questions_available` is
//! a **lower bound**, and `subjects_ready` names the subjects that can fill a
//! slot today. A consumer can therefore tell a real mock from an empty shell
//! before assembling anything.

use axum::Json;
use axum::Router;
use axum::extract::{Path, Query, State};
use axum::routing::get;
use serde::Deserialize;

use crate::AppState;
use crate::bank::Scheme;
use crate::bank::scheme;
use crate::error::ApiError;

/// The scheme plus whether the bank can fill it. Readiness is kept beside the
/// scheme rather than inside it, so the shape a consumer validates does not
/// move when our content grows.
#[derive(serde::Serialize, utoipa::ToSchema)]
pub struct PaperReadiness {
    pub exam: String,
    pub scheme: Scheme,
    /// True when every requirement group for the scheme's country scope
    /// holds enough verified questions.
    pub complete: bool,
}

#[derive(Deserialize)]
pub struct PapersQuery {
    /// Country scope, e.g. `GH`. A one-country exam implies its own;
    /// anything else needs it said out loud, and completeness is only
    /// ever claimed for a scope.
    pub country: Option<String>,
}

pub fn router() -> Router<AppState> {
    Router::new().route("/v1/exams/{exam}/papers", get(readiness))
}

#[utoipa::path(
    get,
    path = "/api/v1/exams/{exam}/papers",
    tag = "papers",
    operation_id = "getExamScheme",
    params(
        ("exam" = String, Path, description = "Exam code, as listed by GET /exams."),
        ("country" = Option<String>, Query, description = "Country scope, e.g. GH."),
    ),
    responses(
        (status = 200, body = PaperReadiness),
        (status = 404, description = "No subject carried for that exam"),
    ),
)]
pub async fn readiness(
    State(state): State<AppState>,
    Path(exam): Path<String>,
    Query(f): Query<PapersQuery>,
) -> Result<Json<PaperReadiness>, ApiError> {
    let scheme = scheme::scheme_for(state.bank.as_ref(), &exam, f.country.as_deref())
        .ok_or_else(|| ApiError::not_found("exam_not_found", &exam))?;
    let complete = scheme.is_complete();
    Ok(Json(PaperReadiness {
        exam,
        scheme,
        complete,
    }))
}
