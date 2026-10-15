//! `/api/v1/novels` — the novel domain (D35).
//!
//! Public like the rest of the catalog: a student deciding whether to read the
//! book should not need a key to see what it is. Questions stay behind auth.

use axum::Json;
use axum::Router;
use axum::extract::{Path, Query, State};
use axum::routing::get;
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

use crate::AppState;
use crate::api::auth::Caller;
use crate::bank::DEFAULT_PER_PAGE;
use crate::bank::{Novel, NovelDoc, render_novel_question};
use crate::error::ApiError;

#[derive(Serialize, ToSchema)]
pub struct NovelList {
    pub novels: Vec<Novel>,
}

#[derive(Deserialize)]
pub struct NovelFilter {
    pub exam: Option<String>,
    pub year: Option<u16>,
    /// Only the featured (current set text) ones.
    pub featured: Option<bool>,
    /// `english` (Use-of-English reading text) or `literature` (prescribed text).
    pub category: Option<String>,
}

#[derive(Serialize, ToSchema)]
pub struct NovelQuestionPage {
    pub questions: Vec<crate::bank::RenderedNovelQuestion>,
    pub page: u32,
    pub per_page: u32,
    pub total_pages: u32,
    pub total_records: usize,
    pub includes_explanation: bool,
}

#[derive(Deserialize)]
pub struct NovelQuestionsQuery {
    pub chapter: Option<u8>,
    pub include_explanation: Option<bool>,
    pub page: Option<u32>,
    pub per_page: Option<u32>,
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/v1/novels", get(list))
        .route("/v1/novels/{id}", get(detail))
        .route("/v1/novels/{id}/questions", get(questions))
}

#[utoipa::path(
    get,
    path = "/api/v1/novels",
    tag = "novels",
    operation_id = "listNovels",
    summary = "Prescribed texts for an exam cycle.",
    description = "All novels, newest prescription first. No key required.",
    params(
        ("exam" = Option<String>, Query, description = "Scope to an exam."),
        ("year" = Option<u16>, Query, description = "Prescription year, e.g. 2025."),
        ("featured" = Option<bool>, Query, description = "Only the current set text."),
        ("category" = Option<String>, Query,
         description = "english (reading text) or literature (prescribed text)."),
    ),
    responses((status = 200, body = NovelList)),
)]
pub async fn list(State(state): State<AppState>, Query(f): Query<NovelFilter>) -> Json<NovelList> {
    let bank = state.bank.borrow().clone();
    let mut novels: Vec<Novel> = bank
        .novels(f.exam.as_deref())
        .into_iter()
        .filter(|n| f.year.is_none_or(|y| n.year_prescribed.contains(&y)))
        .filter(|n| f.featured.is_none_or(|want| n.featured == want))
        .filter(|n| f.category.as_deref().is_none_or(|c| n.category == c))
        .cloned()
        .collect();
    novels.sort_by(|a, b| {
        b.year_prescribed
            .cmp(&a.year_prescribed)
            .then_with(|| a.title.cmp(&b.title))
    });
    Json(NovelList { novels })
}

#[utoipa::path(
    get,
    path = "/api/v1/novels/{id}",
    tag = "novels",
    operation_id = "getNovel",
    summary = "One novel: chapters, characters, themes.",
    description = "One novel: book, chapters, characters, themes. No key required.",
    params(("id" = String, Path, description = "Novel id, e.g. lekki-headmaster.")),
    responses(
        (status = 200, body = NovelDoc),
        (status = 404, description = "No such novel"),
    ),
)]
pub async fn detail(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<NovelDoc>, ApiError> {
    let bank = state.bank.borrow().clone();
    bank.novel(&id)
        .map(|n| Json(n.clone()))
        .ok_or_else(|| ApiError::not_found("novel_not_found", format!("No novel with id '{id}'.")))
}

#[utoipa::path(
    get,
    path = "/api/v1/novels/{id}/questions",
    tag = "novels",
    operation_id = "listNovelQuestions",
    summary = "Quiz rows for one novel.",
    description = "Quiz items for one novel, paged. The answer is withheld unless asked.",
    params(
        ("id" = String, Path, description = "Novel id."),
        ("chapter" = Option<u8>, Query, description = "Drill one chapter."),
        ("include_explanation" = Option<bool>, Query,
         description = "Include the answer and the working. Default: false."),
        ("page" = Option<u32>, Query, description = "1-based page number. Default: 1."),
        ("per_page" = Option<u32>, Query,
         description = "Page size. Default: 50. Capped at 200."),
    ),
    responses(
        (status = 200, body = NovelQuestionPage),
        (status = 401, description = "Missing or invalid API key"),
        (status = 404, description = "No such novel"),
        (status = 429, description = "Over the key's per-minute limit"),
    ),
    security(("ApiKeyAuth" = [])),
)]
pub async fn questions(
    State(state): State<AppState>,
    _caller: Caller,
    Path(id): Path<String>,
    Query(f): Query<NovelQuestionsQuery>,
) -> Result<Json<NovelQuestionPage>, ApiError> {
    use crate::bank::MAX_PER_PAGE;

    let bank = state.bank.borrow().clone();
    let doc = bank.novel(&id).ok_or_else(|| {
        ApiError::not_found("novel_not_found", format!("No novel with id '{id}'."))
    })?;

    let mut matched: Vec<_> = doc
        .questions
        .iter()
        .filter(|q| f.chapter.is_none_or(|ch| q.chapter_number == Some(ch)))
        .collect();
    matched.sort_by(|a, b| a.id.cmp(&b.id));

    let per_page = f
        .per_page
        .unwrap_or(DEFAULT_PER_PAGE)
        .clamp(1, MAX_PER_PAGE);
    let page = f.page.unwrap_or(1).max(1);
    let total_records = matched.len();
    let total_pages = if total_records == 0 {
        0
    } else {
        total_records.div_ceil(per_page as usize) as u32
    };
    let start = (page as usize - 1) * per_page as usize;
    let with_explanation = f.include_explanation.unwrap_or(false);

    Ok(Json(NovelQuestionPage {
        questions: matched
            .into_iter()
            .skip(start)
            .take(per_page as usize)
            .map(|q| render_novel_question(&id, q, with_explanation))
            .collect(),
        page,
        per_page,
        total_pages,
        total_records,
        includes_explanation: with_explanation,
    }))
}
