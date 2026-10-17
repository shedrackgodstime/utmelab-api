use axum::{
    extract::{Path, Query, State},
    routing::get,
    Json, Router,
};
use serde::Deserialize;

use crate::{
    auth::{api_key::AuthedKey, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

#[derive(Deserialize)]
pub struct List {
    pub exam: Option<String>,
    pub year: Option<u16>,
    pub featured: Option<bool>,
    pub category: Option<String>,
}

pub async fn list(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Query(f): Query<List>,
) -> Result<Json<Vec<core::models::Novel>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(
        store::catalog::list_novels(
            &s,
            f.exam.as_deref(),
            f.year,
            f.featured,
            f.category.as_deref(),
        )
        .await?,
    ))
}

pub async fn detail(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
) -> Result<Json<core::models::NovelDoc>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match store::catalog::get_novel_doc(&s, &id).await? {
        Some(d) => Ok(Json(d)),
        None => Err(AppError::NotFound),
    }
}

#[derive(Deserialize)]
pub struct Questions {
    pub chapter: Option<u8>,
    pub include_explanation: Option<bool>,
    pub page: Option<u32>,
    pub per_page: Option<u32>,
}

pub async fn questions(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
    Query(f): Query<Questions>,
) -> Result<Json<core::models::NovelQuestionPage>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let with_explanation = f.include_explanation.unwrap_or(false);
    let (page, per_page) =
        core::catalog::page_bounds(f.page.unwrap_or(1), f.per_page.unwrap_or(50));
    let all = store::catalog::list_novel_questions(&s, &id, f.chapter).await?;
    if all.is_empty() && store::catalog::get_novel_doc(&s, &id).await?.is_none() {
        return Err(AppError::NotFound);
    }
    let total_records = all.len();
    let start = ((page - 1) * per_page) as usize;
    let rendered = all
        .into_iter()
        .skip(start)
        .take(per_page as usize)
        .map(|q| core::catalog::render_novel_question(&id, &q, with_explanation))
        .collect();
    Ok(Json(core::models::Page::new(
        rendered,
        page,
        per_page,
        total_records,
        with_explanation,
    )))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/novels", get(list))
        .route("/v1/novels/{id}", get(detail))
        .route("/v1/novels/{id}/questions", get(questions))
        .with_state(state)
}
