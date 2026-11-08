use axum::{
    extract::{Path, State},
    routing::get,
    Json, Router,
};

use crate::{
    auth::{api_key::AuthedKey, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

#[utoipa::path(
    get,
    path = "/api/v1/notes/{exam}/{subject}/{topic_slug}",
    tag = "catalog",
    operation_id = "getTopicNote",
    summary = "High-yield study note for a syllabus topic.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `JAMB`."),
        ("subject" = String, Path, description = "Subject slug, e.g. `physics`."),
        ("topic_slug" = String, Path, description = "Topic slug, e.g. `motion`."),
    ),
    responses(
        (status = 200, body = core::models::TopicNote),
        (status = 404, description = "No note found for this topic", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn topic_note(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject, topic_slug)): Path<(String, String, String)>,
) -> Result<Json<core::models::TopicNote>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match store::catalog::get_topic_note(&s, &exam, &subject, &topic_slug).await? {
        Some(n) => Ok(Json(n)),
        None => Err(AppError::NotFound),
    }
}

#[utoipa::path(
    get,
    path = "/api/v1/notes/subtopic/{exam}/{subject}/{subtopic_slug}",
    tag = "catalog",
    operation_id = "getSubtopicNote",
    summary = "High-yield study note for a specific syllabus subtopic.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `JAMB`."),
        ("subject" = String, Path, description = "Subject slug, e.g. `physics`."),
        ("subtopic_slug" = String, Path, description = "Subtopic slug, e.g. `projectiles`."),
    ),
    responses(
        (status = 200, body = core::models::TopicNote),
        (status = 404, description = "No note found for this subtopic", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn subtopic_note(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject, subtopic_slug)): Path<(String, String, String)>,
) -> Result<Json<core::models::TopicNote>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match store::catalog::get_subtopic_note(&s, &exam, &subject, &subtopic_slug).await? {
        Some(n) => Ok(Json(n)),
        None => Err(AppError::NotFound),
    }
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/notes/{exam}/{subject}/{topic_slug}", get(topic_note))
        .route(
            "/v1/notes/subtopic/{exam}/{subject}/{subtopic_slug}",
            get(subtopic_note),
        )
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::testing::{api_schema, bank_schema, call, connect, issue_key, replica, state};
    use axum::http::StatusCode;

    async fn seeded_app() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["exams", "subjects", "topics"]).await;

        conn.execute(
            "INSERT INTO topic_notes (id, exam, subject, topic_slug, subtopic_slug, title, read_time_minutes, key_takeaway, sections, worked_examples, formulas, active_recall_checks, examiner_traps, linked_question_ids, content_hash) \
             VALUES ('note_1', 'JAMB', 'physics', 'motion', NULL, 'Motion Overview', 3, '{\"text\":\"Motion is change in position.\",\"inline\":[]}', '[]', '[]', '[]', '[]', '[]', '[]', 'hash1')",
            (),
        )
        .await
        .expect("insert topic note");

        conn.execute(
            "INSERT INTO topic_notes (id, exam, subject, topic_slug, subtopic_slug, title, read_time_minutes, key_takeaway, sections, worked_examples, formulas, active_recall_checks, examiner_traps, linked_question_ids, content_hash) \
             VALUES ('note_2', 'JAMB', 'physics', 'motion', 'projectiles', 'Projectile Motion', 5, '{\"text\":\"2D motion.\",\"inline\":[]}', '[]', '[]', '[]', '[]', '[]', '[]', 'hash2')",
            (),
        )
        .await
        .expect("insert subtopic note");

        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        issue_key(&conn, "wrong.secret", "commercial", "write:reports", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    #[tokio::test]
    async fn topic_note_is_keyed_and_scoped() {
        let app = seeded_app().await;

        // Missing key -> 401
        assert_eq!(
            call(app.clone(), "GET", "/api/v1/notes/JAMB/physics/motion", None, None).await.0,
            StatusCode::UNAUTHORIZED
        );

        // Wrong scope -> 403
        assert_eq!(
            call(app.clone(), "GET", "/api/v1/notes/JAMB/physics/motion", Some("wrong.secret"), None).await.0,
            StatusCode::FORBIDDEN
        );

        // Valid key -> 200
        let (status, body) = call(app.clone(), "GET", "/api/v1/notes/JAMB/physics/motion", Some("reader.secret"), None).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["id"], "note_1");
        assert_eq!(body["title"], "Motion Overview");

        // Subtopic note -> 200
        let (status, body) = call(app.clone(), "GET", "/api/v1/notes/subtopic/JAMB/physics/projectiles", Some("reader.secret"), None).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["id"], "note_2");
        assert_eq!(body["title"], "Projectile Motion");

        // Absent note -> 404
        assert_eq!(
            call(app, "GET", "/api/v1/notes/JAMB/physics/nonexistent", Some("reader.secret"), None).await.0,
            StatusCode::NOT_FOUND
        );
    }
}
