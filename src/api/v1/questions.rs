//! `/api/v1/questions` — the metered surface.
//!
//! Requires a key. Two rules apply to every response here:
//!
//! * **Paged** (D3/D30). `per_page` defaults to 50 and is capped at 200, so no
//!   single request can ask for the whole bank.
//! * **The answer is withheld** unless explicitly requested (D27). A quiz
//!   consumer needs the stem first, and an answer riding along in a default
//!   payload gets rendered by somebody, eventually, by accident.

use axum::Json;
use axum::Router;
use axum::extract::{Path, Query, State};
use axum::routing::get;
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

use crate::AppState;
use crate::api::auth::Caller;
use crate::bank::{DEFAULT_PER_PAGE, QuestionFilter};
use crate::bank::{RenderedQuestion, render};
use crate::error::ApiError;

/// The paged response envelope (D3/D30).
#[derive(Serialize, ToSchema)]
pub struct QuestionPage {
    pub questions: Vec<RenderedQuestion>,
    /// 1-based.
    pub page: u32,
    pub per_page: u32,
    pub total_pages: u32,
    pub total_records: usize,
    /// Whether `answer` and `explanation` were included (D27).
    pub includes_explanation: bool,
}

#[derive(Deserialize)]
pub struct Filter {
    pub exam: Option<String>,
    pub subject: Option<String>,
    pub subtopic: Option<String>,
    pub verified: Option<bool>,
    /// Provenance filter: `past_paper`, `claimed_paper`, `authored` or
    /// `imported`. Says where the question came from; `year` says which exam
    /// cohort it is prepared for.
    pub source: Option<String>,
    /// Only questions prepared for this exam year, e.g. `2025`.
    pub year: Option<u16>,
    /// Substring of the question text, case-insensitive. No ranking: results
    /// stay in id order, so paging means the same thing it means everywhere
    /// else (D44).
    pub q: Option<String>,
    /// Country code filter through subtopic → topic scope, e.g. `GH`.
    /// Untagged questions are unscoped and always included. Absent means
    /// the full honest view, never an assumed country.
    pub country: Option<String>,
    /// Opt in to the answer and the working.
    pub include_explanation: Option<bool>,
    /// 1-based.
    pub page: Option<u32>,
    pub per_page: Option<u32>,
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/v1/questions", get(questions))
        .route("/v1/questions/{id}", get(question_by_id))
}

/// The query a single-row fetch accepts. Same opt-in as the list, so a consumer
/// can resolve a saved id with the same call it already uses to page.
#[derive(Deserialize)]
pub struct Detail {
    pub include_explanation: Option<bool>,
}

/// One question, addressed by the id we handed out.
///
/// Exists because every consumer that stores an id — a saved question, a report
/// receipt, a deep link — otherwise has no way back to the row. Same route
/// shape as `/novels/{id}` and `/passages/{id}`; the store seam already had
/// `Store::question()` for it.
#[utoipa::path(
    get,
    path = "/api/v1/questions/{id}",
    tag = "questions",
    operation_id = "getQuestion",
    summary = "One question by id.",
    description = "One question by id, shaped exactly like an item from `/questions`.\n\nThe answer \
is withheld unless `include_explanation=true`, the same rule the list follows.",
    params(
        ("id" = String, Path, description = "A question id, exactly as returned by `/questions`."),
        ("include_explanation" = Option<bool>, Query,
         description = "Include the answer and the working. Default: false."),
    ),
    responses(
        (status = 200, body = RenderedQuestion),
        (status = 401, description = "Missing or invalid API key"),
        (status = 404, description = "No question with that id"),
    ),
)]
pub async fn question_by_id(
    State(state): State<AppState>,
    _caller: Caller,
    Path(id): Path<String>,
    Query(f): Query<Detail>,
) -> Result<Json<RenderedQuestion>, ApiError> {
    let bank = state.bank.borrow().clone();
    let question = bank.question(&id).ok_or_else(|| {
        ApiError::not_found("question_not_found", format!("No question with id '{id}'."))
    })?;

    Ok(Json(render(
        question,
        f.include_explanation.unwrap_or(false),
    )))
}

#[utoipa::path(
    get,
    path = "/api/v1/questions",
    tag = "questions",
    operation_id = "listQuestions",
    summary = "Paged questions, answers withheld by default.",
    description = "Paged, and the answer is withheld unless you ask for it.\n\n**The answer \
is only in the response when `include_explanation=true`.** A quiz consumer needs the stem \
first, and an answer in a default payload gets rendered by somebody, eventually, by \
accident.\n\nRender option labels from array position: ids are stable identity, labels are \
display.",
    params(
        ("subtopic" = Option<String>, Query, description = "Drill one subtopic."),
        ("exam" = Option<String>, Query, description = "Scope to an exam."),
        ("subject" = Option<String>, Query, description = "Scope to a subject within that exam."),
        ("verified" = Option<bool>, Query,
         description = "Only human-checked questions. Default: no filter."),
        ("year" = Option<u16>, Query,
         description = "Only questions prepared for this exam year. Default: no filter."),
        ("source" = Option<String>, Query,
         description = "Provenance: `past_paper`, `authored` or `imported`. Default: no filter."),
        ("q" = Option<String>, Query,
         description = "Substring of the question text, case-insensitive. Unranked — results stay \
in id order. Default: no filter."),
        ("country" = Option<String>, Query,
         description = "Country code filter through subtopic scope, e.g. GH. Default: no filter."),
        // utoipa cannot emit a `default` on a query parameter, so the defaults
        // are stated in the description — a client reads them there anyway.
        ("include_explanation" = Option<bool>, Query,
         description = "Include the answer and the working. Default: false."),
        ("page" = Option<u32>, Query, description = "1-based page number. Default: 1."),
        ("per_page" = Option<u32>, Query,
         description = "Page size. Default: 50. Capped at 200."),
    ),
    responses(
        (status = 200, body = QuestionPage),
        (status = 401, description = "Missing or invalid API key"),
        (status = 404, description = "No such subject, or no usable filter"),
        (status = 429, description = "Over the key's per-minute limit"),
    ),
    security(("ApiKeyAuth" = [])),
)]
pub async fn questions(
    State(state): State<AppState>,
    _caller: Caller,
    Query(f): Query<Filter>,
) -> Result<Json<QuestionPage>, ApiError> {
    let bank = state.bank.borrow().clone();
    // Reject a filter that names a subject this exam does not offer, rather
    // than returning a confident empty list.
    if let (Some(exam), Some(subject)) = (&f.exam, &f.subject) {
        if f.subtopic.is_none() && bank.subject(exam, subject).is_none() {
            return Err(ApiError::not_found(
                "subject_not_found",
                format!("No subject with slug '{subject}' for exam '{exam}'."),
            ));
        }
    }

    let page = bank.questions_page(
        QuestionFilter {
            exam: f.exam.as_deref(),
            subject: f.subject.as_deref(),
            subtopic: f.subtopic.as_deref(),
            verified: f.verified,
            text: f.q.as_deref(),
            source: f.source.as_deref(),
            year: f.year,
            country: f.country.as_deref(),
        },
        f.page.unwrap_or(1),
        f.per_page.unwrap_or(DEFAULT_PER_PAGE),
    );

    let with_explanation = f.include_explanation.unwrap_or(false);

    Ok(Json(QuestionPage {
        questions: page
            .questions
            .iter()
            .map(|q| render(q, with_explanation))
            .collect(),
        page: page.page,
        per_page: page.per_page,
        total_pages: page.total_pages(),
        total_records: page.total_records,
        includes_explanation: with_explanation,
    }))
}
