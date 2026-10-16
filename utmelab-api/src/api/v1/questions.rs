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
pub struct Detail {
    pub include_explanation: Option<bool>,
}

pub async fn one(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
    Query(f): Query<Detail>,
) -> Result<Json<core::models::RenderedQuestion>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match store::catalog::get_question(&s, &id).await? {
        Some(q) => Ok(Json(core::catalog::render(
            &q,
            f.include_explanation.unwrap_or(false),
        ))),
        None => Err(AppError::NotFound),
    }
}

#[derive(Deserialize)]
pub struct List {
    pub subtopic: Option<String>,
    pub exam: Option<String>,
    pub subject: Option<String>,
    pub verified: Option<bool>,
    pub year: Option<u16>,
    pub source: Option<String>,
    pub q: Option<String>,
    pub country: Option<String>,
    pub include_explanation: Option<bool>,
    pub page: Option<u32>,
    pub per_page: Option<u32>,
}

pub async fn list(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Query(f): Query<List>,
) -> Result<Json<core::models::QuestionPageResponse>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    if f.verified.is_some() {
        return Err(AppError::BadRequest(
            "verified filter not yet supported".to_string(),
        ));
    }
    if f.country.is_some() {
        return Err(AppError::BadRequest(
            "country filter not yet supported".to_string(),
        ));
    }
    // A filter naming a combination the bank never had must 404, not
    // return a confident empty list.
    if let (Some(exam), Some(subject)) = (&f.exam, &f.subject) {
        if f.subtopic.is_none() && !store::catalog::subject_exists(&s, exam, subject).await? {
            return Err(AppError::NotFound);
        }
    }
    let filter = store::catalog::QuestionFilter {
        exam: f.exam.clone(),
        subject: f.subject.clone(),
        subtopic_id: f.subtopic.clone(),
        year: f.year,
        source: f.source.clone(),
        text: f.q.clone(),
    };
    let with_explanation = f.include_explanation.unwrap_or(false);
    let (page, per_page) =
        core::catalog::page_bounds(f.page.unwrap_or(1), f.per_page.unwrap_or(50));
    let (questions, total_records) =
        store::catalog::list_questions(&s, &filter, page, per_page).await?;
    Ok(Json(core::models::QuestionPageResponse {
        questions: questions
            .iter()
            .map(|q| core::catalog::render(q, with_explanation))
            .collect(),
        page,
        per_page,
        total_pages: if total_records == 0 {
            0
        } else {
            total_records.div_ceil(per_page as usize) as u32
        },
        total_records,
        includes_explanation: with_explanation,
    }))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/questions", get(list))
        .route("/v1/questions/{id}", get(one))
        .with_state(state)
}
