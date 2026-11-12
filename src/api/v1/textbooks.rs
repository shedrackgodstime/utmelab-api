//! The textbook surface: books, chapters, sections and exercises.
//!
//! These routes carry the teaching half of the platform. The exam half
//! (traps and practice written in an exam's wording) hangs off the same
//! chapter sections, and the exam pack joins the two.

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
    store::{self, chapters::ChapterSummary},
};

/// A book with the chapters it holds.
#[derive(Clone, Debug, serde::Serialize, utoipa::ToSchema)]
pub struct BookWithChapters {
    pub id: String,
    pub title: String,
    pub subject_area: String,
    pub level: String,
    pub edition: String,
    pub description: String,
    pub parts: Vec<crate::core::models::BookPart>,
    pub chapters: Vec<ChapterSummary>,
}

#[utoipa::path(
    get,
    path = "/api/v1/textbooks",
    tag = "textbook",
    operation_id = "listTextbooks",
    summary = "Every book, with the subject area and the level it teaches.",
    responses(
        (status = 200, body = Vec<crate::core::models::Book>),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn list_textbooks(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
) -> Result<Json<Vec<crate::core::models::Book>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(store::chapters::list_books(&s).await?))
}

#[utoipa::path(
    get,
    path = "/api/v1/textbooks/{book_id}",
    tag = "textbook",
    operation_id = "getTextbook",
    summary = "One book and the chapters it holds.",
    params(("book_id" = String, Path, description = "Book id, e.g. `secondary_physics`.")),
    responses(
        (status = 200, body = BookWithChapters),
        (status = 404, description = "No book with that id", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn get_textbook(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(book_id): Path<String>,
) -> Result<Json<BookWithChapters>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let Some((book, chapters)) = store::chapters::get_book(&s, &book_id).await? else {
        return Err(AppError::NotFound);
    };
    Ok(Json(BookWithChapters {
        id: book.id,
        title: book.title,
        subject_area: book.subject_area,
        level: book.level,
        edition: book.edition,
        description: book.description,
        parts: book.parts,
        chapters,
    }))
}

#[utoipa::path(
    get,
    path = "/api/v1/chapters/{chapter_id}",
    tag = "textbook",
    operation_id = "getChapter",
    summary = "One chapter: its sections, its exercises and its exam side.",
    params(("chapter_id" = String, Path, description = "Chapter id, e.g. `phy_forces_and_newtons_laws`.")),
    responses(
        (status = 200, body = crate::core::models::Chapter),
        (status = 404, description = "No chapter with that id", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn get_chapter(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(chapter_id): Path<String>,
) -> Result<Json<crate::core::models::Chapter>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let Some(mut chapter) = store::chapters::get_chapter(&s, &chapter_id).await? else {
        return Err(AppError::NotFound);
    };
    for section in &mut chapter.sections {
        core::catalog::resolve_teaching_text(&mut section.teaching_text, s.media_base_url.as_ref());
    }
    Ok(Json(chapter))
}

/// Narrow an exercise list to a section or a tier.
#[derive(Clone, Debug, Default, Deserialize, utoipa::IntoParams)]
pub struct ExerciseQuery {
    /// Only the exercises of this section.
    pub section_id: Option<String>,
    /// Only the exercises of this tier: `warm_up`, `core` or `stretch`.
    pub tier: Option<String>,
}

#[utoipa::path(
    get,
    path = "/api/v1/chapters/{chapter_id}/exercises",
    tag = "textbook",
    operation_id = "listChapterExercises",
    summary = "The exercises of a chapter, each with its answer and its solution.",
    params(
        ("chapter_id" = String, Path, description = "Chapter id."),
        ExerciseQuery,
    ),
    responses(
        (status = 200, body = Vec<crate::core::models::ChapterExercise>),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn list_chapter_exercises(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(chapter_id): Path<String>,
    Query(query): Query<ExerciseQuery>,
) -> Result<Json<Vec<crate::core::models::ChapterExercise>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let exercises = store::chapters::list_exercises(
        &s,
        &chapter_id,
        query.section_id.as_deref(),
        query.tier.as_deref(),
    )
    .await?;
    Ok(Json(exercises))
}

/// Narrow a trap list to an exam or a section.
#[derive(Clone, Debug, Default, Deserialize, utoipa::IntoParams)]
pub struct TrapQuery {
    /// Only the traps of this exam, e.g. `JAMB`.
    pub exam: Option<String>,
    /// Only the traps of this section.
    pub section_id: Option<String>,
}

#[utoipa::path(
    get,
    path = "/api/v1/exam-traps",
    tag = "textbook",
    operation_id = "listExamTraps",
    summary = "The mistakes candidates make, with the evidence behind each one.",
    params(TrapQuery),
    responses(
        (status = 200, body = Vec<crate::core::models::ExamTrap>),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn list_exam_traps(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Query(query): Query<TrapQuery>,
) -> Result<Json<Vec<crate::core::models::ExamTrap>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let traps =
        store::chapters::list_traps(&s, query.exam.as_deref(), query.section_id.as_deref()).await?;
    Ok(Json(traps))
}

/// Narrow a practice list to an exam or a section.
#[derive(Clone, Debug, Default, Deserialize, utoipa::IntoParams)]
pub struct RecallQuery {
    /// Only the practice items of this exam, e.g. `WAEC`.
    pub exam: Option<String>,
    /// Only the practice items of this section.
    pub section_id: Option<String>,
}

#[utoipa::path(
    get,
    path = "/api/v1/exam-practice",
    tag = "textbook",
    operation_id = "listExamPractice",
    summary = "Practice items written in an exam's own wording.",
    params(RecallQuery),
    responses(
        (status = 200, body = Vec<crate::core::models::ExamRecallCheck>),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn list_exam_practice(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Query(query): Query<RecallQuery>,
) -> Result<Json<Vec<crate::core::models::ExamRecallCheck>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let checks =
        store::chapters::list_recall_checks(&s, query.exam.as_deref(), query.section_id.as_deref())
            .await?;
    Ok(Json(checks))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/textbooks", get(list_textbooks))
        .route("/v1/textbooks/{book_id}", get(get_textbook))
        .route("/v1/chapters/{chapter_id}", get(get_chapter))
        .route(
            "/v1/chapters/{chapter_id}/exercises",
            get(list_chapter_exercises),
        )
        .route("/v1/exam-traps", get(list_exam_traps))
        .route("/v1/exam-practice", get(list_exam_practice))
        .with_state(state)
}
