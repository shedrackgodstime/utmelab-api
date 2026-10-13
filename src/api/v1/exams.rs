//! `/api/v1/exams` — the discovery surface.
//!
//! Public by design (D26): an integrator can list exams and subjects before
//! they hold a key. This is what they hit first, so it must need nothing.

use axum::Json;
use axum::Router;
use axum::extract::{Path, State};
use axum::routing::get;
use serde::Serialize;
use utoipa::ToSchema;

use crate::AppState;
use crate::bank::Subject;
use crate::error::ApiError;

#[derive(Serialize, ToSchema)]
pub struct ExamList {
    pub exams: Vec<Exam>,
}

/// One exam, as recorded (D66) plus its live subject count. Nulls are
/// load-bearing: a null the API states is a fact it cannot state.
#[derive(Serialize, ToSchema)]
pub struct Exam {
    /// Exam code, e.g. `JAMB`.
    pub code: String,
    pub name: String,
    pub countries: Vec<String>,
    pub status: crate::bank::ExamStatus,
    pub has_full_paper: Option<bool>,
    pub subjects_required: Option<u32>,
    pub duration_minutes: Option<u32>,
    pub rules: Vec<String>,
    pub subject_count: usize,
}

/// One exam's subject list.
#[derive(Serialize, ToSchema)]
pub struct ExamSubjects {
    pub exam: String,
    pub subjects: Vec<Subject>,
}

/// A single subject, wrapped so the response is one shape rather than a bare
/// object or a one-key envelope depending on the caller.
#[derive(Serialize, ToSchema)]
pub struct SubjectEnvelope {
    pub subject: Subject,
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/v1/exams", get(list))
        .route("/v1/exams/{exam}/subjects", get(subjects))
}

#[utoipa::path(
    get,
    path = "/api/v1/exams",
    tag = "catalog",
    operation_id = "listExams",
    responses((status = 200, body = ExamList)),
)]
pub async fn list(State(state): State<AppState>) -> Json<ExamList> {
    Json(ExamList {
        exams: state
            .bank
            .exams()
            .into_iter()
            .filter_map(|code| {
                let rec = state.bank.exam(code)?;
                Some(Exam {
                    code: rec.code.clone(),
                    name: rec.name.clone(),
                    countries: rec.countries.clone(),
                    status: rec.status,
                    has_full_paper: rec.has_full_paper,
                    subjects_required: rec.subjects_required,
                    duration_minutes: rec.duration_minutes,
                    rules: rec.rules.clone(),
                    subject_count: state.bank.subjects(code).len(),
                })
            })
            .collect(),
    })
}

#[utoipa::path(
    get,
    path = "/api/v1/exams/{exam}/subjects",
    tag = "catalog",
    operation_id = "listSubjects",
    params(("exam" = String, Path, description = "Exam code, e.g. JAMB")),
    responses(
        (status = 200, body = ExamSubjects),
        (status = 404, description = "No such exam"),
    ),
)]
pub async fn subjects(
    State(state): State<AppState>,
    Path(exam): Path<String>,
) -> Result<Json<ExamSubjects>, ApiError> {
    let subjects = state.bank.subjects(&exam);
    if subjects.is_empty() {
        return Err(ApiError::not_found(
            "exam_not_found",
            format!("No exam named '{exam}'."),
        ));
    }
    Ok(Json(ExamSubjects {
        exam,
        subjects: subjects.into_iter().cloned().collect(),
    }))
}
