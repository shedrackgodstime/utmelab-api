//! `/api/v1/subjects/{exam}/{slug}` — one subject, and its syllabus.
//!
//! The exam is in the path because it is part of a subject's identity (D21):
//! `use-of-english` exists for JAMB and not for WAEC, which spells it
//! `english-language`.

use axum::Json;
use axum::Router;
use axum::extract::{Path, State};
use axum::routing::get;

use super::exams::SubjectEnvelope;
use crate::AppState;
use crate::bank::{Subject, Syllabus, SyllabusSummary};
use crate::error::ApiError;
use serde::Serialize;
use utoipa::ToSchema;

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/v1/subjects/{exam}/{slug}", get(subject))
        .route("/v1/subjects/{exam}/{slug}/syllabus", get(syllabus))
        .route("/v1/subjects/{exam}/{slug}/coverage", get(coverage))
}

#[utoipa::path(
    get,
    path = "/api/v1/subjects/{exam}/{slug}",
    tag = "catalog",
    operation_id = "getSubject",
    params(
        ("exam" = String, Path, description = "Exam code."),
        ("slug" = String, Path, description = "The exam's own name for this subject."),
    ),
    responses(
        (status = 200, body = SubjectEnvelope),
        (status = 404, description = "No such subject in that exam"),
    ),
)]
pub async fn subject(
    State(state): State<AppState>,
    Path((exam, slug)): Path<(String, String)>,
) -> Result<Json<SubjectEnvelope>, ApiError> {
    state
        .bank
        .subject(&exam, &slug)
        .map(|subject| {
            Json(SubjectEnvelope {
                subject: subject.clone(),
            })
        })
        .ok_or_else(|| not_found(&exam, &slug))
}

#[utoipa::path(
    get,
    path = "/api/v1/subjects/{exam}/{slug}/syllabus",
    tag = "catalog",
    operation_id = "getSyllabus",
    description = "The whole topic tree for one subject, with a question count and objectives \
on every node — what you must be able to do, beside what you can actually practise. A topic \
with no questions does not appear.",
    params(
        ("exam" = String, Path, description = "Exam code."),
        ("slug" = String, Path, description = "Subject slug within that exam."),
    ),
    responses(
        (status = 200, body = Syllabus),
        (status = 404, description = "No such subject in that exam"),
    ),
)]
pub async fn syllabus(
    State(state): State<AppState>,
    Path((exam, slug)): Path<(String, String)>,
) -> Result<Json<Syllabus>, ApiError> {
    state
        .bank
        .syllabus(&exam, &slug)
        .map(Json)
        .ok_or_else(|| not_found(&exam, &slug))
}

/// Counts without the tree — for progress bars and checklists.
#[derive(Serialize, ToSchema)]
pub struct Coverage {
    pub exam: String,
    pub subject: Subject,
    pub summary: SyllabusSummary,
}

fn not_found(exam: &str, slug: &str) -> ApiError {
    ApiError::not_found(
        "subject_not_found",
        format!("No subject with slug '{slug}' for exam '{exam}'."),
    )
}

/// Coverage without the tree: counts only, for progress bars and checklists.
#[utoipa::path(
    get,
    path = "/api/v1/subjects/{exam}/{slug}/coverage",
    tag = "catalog",
    operation_id = "getCoverage",
    description = "How much of this subject you can practise — counts only, no topic tree.",
    params(
        ("exam" = String, Path, description = "Exam code."),
        ("slug" = String, Path, description = "Subject slug within that exam."),
    ),
    responses(
        (status = 200, body = Coverage),
        (status = 404, description = "No such subject in that exam"),
    ),
)]
pub async fn coverage(
    State(state): State<AppState>,
    Path((exam, slug)): Path<(String, String)>,
) -> Result<Json<Coverage>, ApiError> {
    state
        .bank
        .syllabus(&exam, &slug)
        .map(|s| {
            Json(Coverage {
                exam: s.exam,
                subject: s.subject,
                summary: s.summary,
            })
        })
        .ok_or_else(|| not_found(&exam, &slug))
}
