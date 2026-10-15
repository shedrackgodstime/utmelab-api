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
//!
//! `POST /api/v1/papers/{exam}/{subject}` assembles one subject's mock from
//! ready topics (D69): deterministic per seed, answers always withheld, 409
//! naming the gaps until D68 says complete. Scoring re-assembles with the
//! same seed — stateless, no stored attempts.

use axum::Json;
use axum::Router;
use axum::extract::{Path, Query, State};
use axum::routing::{get, post};
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

use crate::AppState;
use crate::bank::RenderedQuestion;
use crate::bank::Scheme;
use crate::bank::render;
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
    Router::new()
        .route("/v1/exams/{exam}/papers", get(readiness))
        .route("/v1/papers/{exam}/{subject}", post(assemble_paper))
        .route("/v1/papers/{exam}/{subject}/score", post(score_paper))
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
    let bank = state.bank.borrow().clone();
    let scheme = scheme::scheme_for(bank.as_ref(), &exam, f.country.as_deref())
        .ok_or_else(|| ApiError::not_found("exam_not_found", &exam))?;
    let complete = scheme.is_complete();
    Ok(Json(PaperReadiness {
        exam,
        scheme,
        complete,
    }))
}

/// Build the paper for a request, or say exactly why not. Shared by the paper
/// and score endpoints so both refuse identically: one subject lookup, one
/// gate decision, one sentence (D69/D70).
fn build(
    state: &AppState,
    exam: &str,
    subject: &str,
    country: Option<&str>,
    seed: u64,
) -> Result<crate::bank::AssembledPaper, ApiError> {
    let bank = state.bank.borrow().clone();
    if bank.subject(exam, subject).is_none() {
        return Err(ApiError::not_found(
            "subject_not_found",
            format!("No subject with slug '{subject}' for exam '{exam}'."),
        ));
    }
    // Blueprint rows may legitimately be absent: count assembly (D70) needs no
    // measurement, so an empty blueprint is not a 404 — it is a count paper.
    let rows = bank.blueprints(exam, subject);
    crate::bank::assemble(bank.as_ref(), &rows, exam, subject, country, seed)
        .map_err(|unready| ApiError::conflict("paper_not_ready", unready.detail()))
}

#[derive(Serialize, ToSchema)]
pub struct PaperSectionOut {
    pub topic: String,
    pub name: String,
    pub questions: Vec<RenderedQuestion>,
}

#[derive(Serialize, ToSchema)]
pub struct AssembledPaperOut {
    pub exam: String,
    pub subject: String,
    pub seed: u64,
    /// Which gate built this paper (D70): `blueprint` is balanced per
    /// measured topic expectation; `count` is a full-length draw whose mix
    /// is not measured. Consumers must read it before calling the paper fair.
    pub mode: crate::bank::PaperMode,
    pub total: usize,
    pub sections: Vec<PaperSectionOut>,
}

#[derive(Deserialize)]
pub struct AssembleQuery {
    pub seed: Option<u64>,
    pub country: Option<String>,
}

#[derive(Serialize, ToSchema)]
pub struct ReadinessGapOut {
    pub topic: String,
    pub name: String,
    pub expected: f64,
    pub need: u32,
    pub have: usize,
}

#[utoipa::path(
    post,
    path = "/api/v1/papers/{exam}/{subject}",
    tag = "papers",
    operation_id = "assemblePaper",
    description = "Assemble one subject's mock from ready topics (D69): deterministic per seed, answers always withheld. 409 names the gap topics until the subject is complete.",
    params(
        ("exam" = String, Path, description = "Exam code."),
        ("subject" = String, Path, description = "Subject slug within that exam."),
        ("seed" = Option<u64>, Query, description = "Deterministic draw. Same seed, same paper. Default: 1."),
        ("country" = Option<String>, Query, description = "Country code filter, e.g. GH."),
    ),
    responses(
        (status = 200, body = AssembledPaperOut),
        (status = 404, description = "No such subject for this exam"),
        (status = 409, description = "Bank cannot fill the paper; the detail names what is short"),
    ),
)]
pub async fn assemble_paper(
    State(state): State<AppState>,
    Path((exam, subject)): Path<(String, String)>,
    Query(f): Query<AssembleQuery>,
    _caller: crate::api::auth::Caller,
) -> Result<Json<AssembledPaperOut>, ApiError> {
    let paper = build(
        &state,
        &exam,
        &subject,
        f.country.as_deref(),
        f.seed.unwrap_or(1),
    )?;
    Ok(Json(AssembledPaperOut {
        exam: paper.exam.clone(),
        subject: paper.subject.clone(),
        seed: paper.seed,
        mode: paper.mode,
        total: paper.total(),
        sections: paper
            .sections
            .iter()
            .map(|s| PaperSectionOut {
                topic: s.topic.clone(),
                name: s.name.clone(),
                questions: s.questions.iter().map(|q| render(q, false)).collect(),
            })
            .collect(),
    }))
}

#[derive(Deserialize, ToSchema)]
pub struct ScoreRequest {
    /// The seed the paper was assembled with.
    pub seed: u64,
    /// Country scope used at assembly, if any — scope changes the rows.
    pub country: Option<String>,
    /// Candidate's answers: question id → chosen option id.
    pub answers: std::collections::HashMap<String, String>,
}

#[derive(Serialize, ToSchema)]
pub struct ScoredQuestion {
    pub id: String,
    pub submitted: Option<String>,
    pub correct: bool,
}

#[derive(Serialize, ToSchema)]
pub struct ScoreResponse {
    pub exam: String,
    pub subject: String,
    pub seed: u64,
    pub score: usize,
    pub total: usize,
    pub questions: Vec<ScoredQuestion>,
}

#[utoipa::path(
    post,
    path = "/api/v1/papers/{exam}/{subject}/score",
    tag = "papers",
    operation_id = "scorePaper",
    description = "Mark a paper assembled with the same seed (D69): re-assembles statelessly and marks only submitted ids. Unsubmitted rows report unanswered, never the key.",
    params(
        ("exam" = String, Path, description = "Exam code."),
        ("subject" = String, Path, description = "Subject slug within that exam."),
    ),
    request_body = ScoreRequest,
    responses(
        (status = 200, body = ScoreResponse),
        (status = 404, description = "No such subject for this exam"),
        (status = 409, description = "Bank cannot fill the paper; the detail names what is short"),
    ),
)]
pub async fn score_paper(
    State(state): State<AppState>,
    Path((exam, subject)): Path<(String, String)>,
    Json(body): Json<ScoreRequest>,
) -> Result<Json<ScoreResponse>, ApiError> {
    let paper = build(&state, &exam, &subject, body.country.as_deref(), body.seed)?;
    let (score, marked) = crate::bank::mark(&paper, &body.answers);
    let total = paper.total();
    Ok(Json(ScoreResponse {
        exam: paper.exam.clone(),
        subject: paper.subject.clone(),
        seed: paper.seed,
        score,
        total,
        questions: marked
            .into_iter()
            .map(|m| ScoredQuestion {
                id: m.id,
                submitted: m.submitted,
                correct: m.correct,
            })
            .collect(),
    }))
}
