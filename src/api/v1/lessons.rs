//! Exam-neutral lesson content.

use axum::{extract::{Path, State}, routing::get, Json, Router};

use crate::{
    auth::{api_key::AuthedKey, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

#[utoipa::path(
    get,
    path = "/api/v1/lessons/{id}",
    tag = "lessons",
    operation_id = "getLesson",
    summary = "One exam-neutral teaching lesson.",
    params(
        ("id" = String, Path, description = "Lesson id."),
    ),
    responses(
        (status = 200, body = core::models::Lesson),
        (status = 404, description = "No such lesson", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn one(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
) -> Result<Json<core::models::Lesson>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let Some(mut lesson) = store::lessons::get_lesson(&s, &id).await? else {
        return Err(AppError::NotFound);
    };
    core::catalog::resolve_rich_text(&mut lesson.description, s.media_base_url.as_ref());
    for block in &mut lesson.content {
        core::catalog::resolve_content_block(block, s.media_base_url.as_ref());
    }
    Ok(Json(lesson))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/lessons/{id}", get(one))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::testing::{api_schema, call, connect, issue_key, replica, state};
    use axum::http::StatusCode;

    async fn seeded_app() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        crate::testing::bank_schema(&conn, &["questions"]).await;
        conn.execute(
            "INSERT INTO lessons (id, status, title, description, subject, level, estimated_minutes, objectives, content, checks, misconceptions, summary, example_question_refs, provenance, content_hash) VALUES ('lesson-1', 'published', 'Lesson One', '{\"text\":\"Intro\",\"inline\":[]}', 'physics', 'secondary', 10, '[]', '[]', '[]', '[]', '[]', '[{\"id\":\"question-1\",\"title\":\"Question one\"}]', '{}', 'hash-1')",
            (),
        )
        .await
        .expect("lesson");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    #[tokio::test]
    async fn lesson_is_read_by_stable_id_with_example_question_refs() {
        let app = seeded_app().await;
        assert_eq!(
            call(app.clone(), "GET", "/api/v1/lessons/lesson-1", None, None)
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );
        let (status, body) = call(
            app,
            "GET",
            "/api/v1/lessons/lesson-1",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["id"], "lesson-1");
        assert_eq!(body["subject"], "physics");
        assert_eq!(body["example_question_refs"][0]["id"], "question-1");
    }
}
