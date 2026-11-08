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

/// Resolve the exam and subject that own the syllabus a request addresses.
/// NECO and similar boards share another board's syllabus, so the note table
/// is keyed by the owner, not by the requesting board.
async fn resolve_owner(
    s: &DbState,
    exam: &str,
    subject: &str,
) -> Result<(String, String), AppError> {
    if store::catalog::get_exam(s, exam).await?.is_none() {
        return Err(AppError::NotFound);
    }
    let Some(record) = store::catalog::get_subject(s, exam, subject).await? else {
        return Err(AppError::NotFound);
    };
    Ok(core::catalog::syllabus_owner(exam, subject, &record))
}

/// Resolve stored media references, then hold the complete payload to the
/// same 16 KiB transport ceiling the request path uses.
fn prepare_note(
    mut note: core::models::TopicNote,
    media_base_url: &str,
) -> Result<core::models::TopicNote, AppError> {
    core::catalog::resolve_note(&mut note, media_base_url);
    let size = serde_json::to_vec(&note)
        .map_err(|e| AppError::Internal(format!("note serialization failed: {e}")))?
        .len();
    if size >= crate::routes::MAX_BODY_BYTES {
        return Err(AppError::Internal(format!(
            "note {} serializes to {size} bytes, over the {} byte ceiling",
            note.id,
            crate::routes::MAX_BODY_BYTES
        )));
    }
    Ok(note)
}

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
    let (syllabus_exam, syllabus_subject) = resolve_owner(&s, &exam, &subject).await?;
    match store::catalog::get_topic_note(&s, &syllabus_exam, &syllabus_subject, &topic_slug).await?
    {
        Some(note) => Ok(Json(prepare_note(note, s.media_base_url.as_ref())?)),
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
    let (syllabus_exam, syllabus_subject) = resolve_owner(&s, &exam, &subject).await?;
    match store::catalog::get_subtopic_note(&s, &syllabus_exam, &syllabus_subject, &subtopic_slug)
        .await?
    {
        Some(note) => Ok(Json(prepare_note(note, s.media_base_url.as_ref())?)),
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
    use crate::testing::{
        api_schema, bank_schema, call, connect, issue_key, replica, seed_bank_exam,
        seed_bank_subtopic, seed_bank_topic, seed_note, state,
    };
    use axum::http::StatusCode;

    async fn seeded_app() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["exams", "subjects", "topics", "subtopics"]).await;

        seed_bank_exam(&conn, "JAMB", "physics", None).await;
        seed_bank_topic(&conn, "JAMB", "physics", "motion").await;
        seed_bank_subtopic(&conn, "motion", "projectiles").await;
        seed_bank_topic(&conn, "JAMB", "physics", "optics").await;
        seed_bank_topic(&conn, "JAMB", "physics", "waves").await;

        let small = r#"{"text":"Motion is change in position.","inline":[]}"#;
        seed_note(
            &conn, "note_1", "JAMB", "physics", "motion", None, small, "[]",
        )
        .await;
        seed_note(
            &conn,
            "note_2",
            "JAMB",
            "physics",
            "motion",
            Some("projectiles"),
            small,
            "[]",
        )
        .await;

        // Rows exist, but their catalog placement does not.
        seed_note(
            &conn,
            "note_orphan_topic",
            "JAMB",
            "physics",
            "ghost",
            None,
            small,
            "[]",
        )
        .await;
        seed_note(
            &conn,
            "note_orphan_subtopic",
            "JAMB",
            "physics",
            "motion",
            Some("ghost-sub"),
            small,
            "[]",
        )
        .await;

        let media = r#"{"text":"See the figure","inline":[{"start":0,"len":0,"kind":"image","url":"diagram.png","position":"above"}]}"#;
        seed_note(
            &conn,
            "note_media",
            "JAMB",
            "physics",
            "optics",
            None,
            media,
            "[]",
        )
        .await;

        let huge = "x".repeat(17 * 1024);
        let huge_sections = format!(
            r#"[{{"section_number":1,"heading":"Huge","content":{{"text":"{huge}","inline":[]}}}}]"#
        );
        seed_note(
            &conn,
            "note_oversized",
            "JAMB",
            "physics",
            "waves",
            None,
            small,
            &huge_sections,
        )
        .await;

        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        issue_key(&conn, "wrong.secret", "commercial", "write:reports", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    #[tokio::test]
    async fn topic_note_is_keyed_and_scoped() {
        let app = seeded_app().await;

        // Missing key -> 401
        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/notes/JAMB/physics/motion",
                None,
                None
            )
            .await
            .0,
            StatusCode::UNAUTHORIZED
        );

        // Wrong scope -> 403
        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/notes/JAMB/physics/motion",
                Some("wrong.secret"),
                None
            )
            .await
            .0,
            StatusCode::FORBIDDEN
        );

        // Valid key -> 200
        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/notes/JAMB/physics/motion",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["id"], "note_1");
        assert_eq!(body["title"], "note_1 title");

        // Subtopic note -> 200
        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/notes/subtopic/JAMB/physics/projectiles",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["id"], "note_2");
        assert_eq!(body["title"], "note_2 title");

        // Absent note -> 404
        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/notes/JAMB/physics/nonexistent",
                Some("reader.secret"),
                None
            )
            .await
            .0,
            StatusCode::NOT_FOUND
        );

        // A stored note without a catalog topic is never served.
        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/notes/JAMB/physics/ghost",
                Some("reader.secret"),
                None
            )
            .await
            .0,
            StatusCode::NOT_FOUND
        );

        // A stored subtopic note without a catalog subtopic is never served.
        assert_eq!(
            call(
                app,
                "GET",
                "/api/v1/notes/subtopic/JAMB/physics/ghost-sub",
                Some("reader.secret"),
                None
            )
            .await
            .0,
            StatusCode::NOT_FOUND
        );
    }

    #[tokio::test]
    async fn note_media_is_resolved_and_the_payload_ceiling_is_enforced() {
        let app = seeded_app().await;

        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/notes/JAMB/physics/optics",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            body["key_takeaway"]["inline"][0]["url"],
            "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/images/diagram.png"
        );

        let (status, _) = call(
            app,
            "GET",
            "/api/v1/notes/JAMB/physics/waves",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    }

    #[tokio::test]
    async fn a_shared_syllabus_note_is_reachable_from_the_requesting_board() {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &["exams", "subjects", "topics", "subtopics", "questions"],
        )
        .await;

        seed_bank_exam(&conn, "WAEC", "physics", None).await;
        seed_bank_topic(&conn, "WAEC", "physics", "motion").await;
        seed_bank_subtopic(&conn, "motion", "projectiles").await;
        seed_bank_exam(&conn, "NECO", "physics", Some(("WAEC", "physics"))).await;

        let small = r#"{"text":"Shared note.","inline":[]}"#;
        seed_note(
            &conn,
            "note_waec_motion",
            "WAEC",
            "physics",
            "motion",
            None,
            small,
            "[]",
        )
        .await;

        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        let app = crate::routes::router(state(db), &crate::config::Config::default());

        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/notes/NECO/physics/motion",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "body: {body}");
        assert_eq!(body["id"], "note_waec_motion");

        let (status, syllabus) = call(
            app,
            "GET",
            "/api/v1/subjects/NECO/physics/syllabus",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(syllabus["topics"][0]["note_id"], "note_waec_motion");
    }

    #[test]
    fn authored_notes_files_are_valid_and_bounded() {
        let dir = std::path::Path::new("data/notes");
        if !dir.exists() {
            return;
        }

        let mut total_notes = 0;
        let entries = match std::fs::read_dir(dir) {
            Ok(e) => e,
            Err(_) => return,
        };

        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }
            let content = match std::fs::read_to_string(&path) {
                Ok(c) => c,
                Err(_) => continue,
            };
            let notes: Vec<crate::core::models::TopicNote> =
                serde_json::from_str(&content).expect("parse notes");
            total_notes += notes.len();

            for note in &notes {
                assert!(note.id.starts_with("note_"), "id must start with note_");
                assert!(!note.title.is_empty(), "title must not be empty");
                assert!(
                    !note.key_takeaway.text.is_empty(),
                    "takeaway must not be empty"
                );
                assert!(!note.sections.is_empty(), "must have at least one section");
                assert!(note.read_time_minutes > 0 && note.read_time_minutes <= 15);

                for check in &note.active_recall_checks {
                    assert_eq!(check.options.len(), 4, "checks must have 4 options");
                    assert!(
                        (check.correct_index as usize) < 4,
                        "correct_index must be < 4"
                    );
                    assert!(!check.prompt.is_empty());
                    assert!(!check.explanation.is_empty());
                }

                for formula in &note.formulas {
                    assert!(!formula.name.is_empty());
                    assert!(!formula.latex.is_empty());
                }

                let serialized = serde_json::to_string(note).expect("serialize note");
                assert!(
                    serialized.len() < 16 * 1024,
                    "note {} payload ({} bytes) must be strictly under 16 KiB",
                    note.id,
                    serialized.len()
                );
            }
        }

        assert!(
            total_notes >= 24,
            "expected at least 24 authored reference notes"
        );
    }
}
