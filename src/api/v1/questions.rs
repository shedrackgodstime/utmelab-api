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
use axum::extract::{Query, State};
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
    /// Opt in to the answer and the working.
    pub include_explanation: Option<bool>,
    /// 1-based.
    pub page: Option<u32>,
    pub per_page: Option<u32>,
}

pub fn router() -> Router<AppState> {
    Router::new().route("/v1/questions", get(questions))
}

#[utoipa::path(
    get,
    path = "/api/v1/questions",
    tag = "questions",
    operation_id = "listQuestions",
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
    // Reject a filter that names a subject this exam does not offer, rather
    // than returning a confident empty list.
    if let (Some(exam), Some(subject)) = (&f.exam, &f.subject) {
        if f.subtopic.is_none() && state.bank.subject(exam, subject).is_none() {
            return Err(ApiError::not_found(
                "subject_not_found",
                format!("No subject with slug '{subject}' for exam '{exam}'."),
            ));
        }
    }

    let page = state.bank.questions_page(
        QuestionFilter {
            exam: f.exam.as_deref(),
            subject: f.subject.as_deref(),
            subtopic: f.subtopic.as_deref(),
            verified: f.verified,
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
