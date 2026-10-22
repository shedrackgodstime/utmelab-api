//! `/api/v1/subjects/{exam}/{slug}`: one subject, its syllabus, and its
//! coverage.
//!
//! The exam is in the path because it is part of a subject's identity (D21):
//! `use-of-english` exists for JAMB and not for WAEC, which spells it
//! `english-language`.

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

#[utoipa::path(
    get,
    path = "/api/v1/exams/{exam}/subjects",
    tag = "catalog",
    operation_id = "listSubjects",
    summary = "Every subject one exam offers.",
    params(("exam" = String, Path, description = "Exam code, e.g. `JAMB`.")),
    responses((status = 200, body = [core::models::Subject])),
)]
pub async fn by_exam(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(exam): Path<String>,
) -> Result<Json<Vec<core::models::Subject>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(store::catalog::list_subjects(&s, &exam).await?))
}

/// One subject offering within an exam.
#[utoipa::path(
    get,
    path = "/api/v1/subjects/{exam}/{slug}",
    tag = "catalog",
    operation_id = "getSubject",
    summary = "One exam's offering of a subject.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `JAMB`."),
        ("slug" = String, Path, description = "Subject slug within the exam, e.g. `physics`."),
    ),
    responses(
        (status = 200, body = core::models::Subject),
        (status = 404, description = "No such subject in this exam"),
    ),
)]
pub async fn subject(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, slug)): Path<(String, String)>,
) -> Result<Json<core::models::Subject>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    store::catalog::get_subject(&s, &exam, &slug)
        .await?
        .map(Json)
        .ok_or(AppError::NotFound)
}

#[derive(Deserialize, utoipa::IntoParams)]
pub struct SyllabusQuery {
    /// Country code filter, e.g. `GH`. Absent is the full honest tree.
    pub country: Option<String>,
}

/// Assemble one subject's tree. A subject the exam never had is 404, not an
/// empty tree. Shared across internal and public syllabus routes.
pub async fn build_syllabus(
    s: &DbState,
    exam: &str,
    slug: &str,
    country: Option<&str>,
) -> Result<core::models::Syllabus, AppError> {
    let Some(subject) = store::catalog::get_subject(s, exam, slug).await? else {
        return Err(AppError::NotFound);
    };
    let tree = store::catalog::list_syllabus(s, exam, slug).await?;
    let counts = store::catalog::subtopic_counts(s, exam, slug, country).await?;
    Ok(core::catalog::assemble_syllabus_from_counts(
        exam, subject, &tree, &counts, country,
    ))
}

/// The whole topic tree with live counts.
#[utoipa::path(
    get,
    path = "/api/v1/subjects/{exam}/{slug}/syllabus",
    tag = "catalog",
    operation_id = "getSyllabus",
    summary = "A subject's topic tree with live counts.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `JAMB`."),
        ("slug" = String, Path, description = "Subject slug within the exam, e.g. `physics`."),
        SyllabusQuery,
    ),
    responses(
        (status = 200, body = core::models::Syllabus),
        (status = 404, description = "No such subject in this exam"),
    ),
)]
pub async fn syllabus(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, slug)): Path<(String, String)>,
    Query(f): Query<SyllabusQuery>,
) -> Result<Json<core::models::Syllabus>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(
        build_syllabus(&s, &exam, &slug, f.country.as_deref()).await?,
    ))
}

/// Coverage without the tree: counts only, for progress bars and checklists.
#[utoipa::path(
    get,
    path = "/api/v1/subjects/{exam}/{slug}/coverage",
    tag = "catalog",
    operation_id = "getCoverage",
    summary = "A subject's counts without the tree.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `JAMB`."),
        ("slug" = String, Path, description = "Subject slug within the exam, e.g. `physics`."),
        SyllabusQuery,
    ),
    responses(
        (status = 200, body = core::models::Coverage),
        (status = 404, description = "No such subject in this exam"),
    ),
)]
pub async fn coverage(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, slug)): Path<(String, String)>,
    Query(f): Query<SyllabusQuery>,
) -> Result<Json<core::models::Coverage>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let s = build_syllabus(&s, &exam, &slug, f.country.as_deref()).await?;
    Ok(Json(core::models::Coverage {
        exam: s.exam,
        subject: s.subject,
        summary: s.summary,
    }))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/exams/{exam}/subjects", get(by_exam))
        .route("/v1/subjects/{exam}/{slug}", get(subject))
        .route("/v1/subjects/{exam}/{slug}/syllabus", get(syllabus))
        .route("/v1/subjects/{exam}/{slug}/coverage", get(coverage))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::testing::{api_schema, bank_schema, call, connect, issue_key, replica, state};
    use axum::http::StatusCode;

    /// Offline replica seeded through a raw connection. Same harness as the
    /// questions handler test: the identity extractor, the scope check, the
    /// store reads, and the assembly, all through the real router.
    async fn seeded_app() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &[
                "subjects",
                "topics",
                "subtopics",
                "questions",
                "verifications",
            ],
        )
        .await;
        conn.execute(
            "INSERT INTO subjects VALUES ('physics','JAMB','Physics',0,40)",
            (),
        )
        .await
        .expect("insert subject");
        conn.execute(
            "INSERT INTO topics VALUES ('mechanics','physics','JAMB','Mechanics',1,0,'[\"state newton laws\"]','[]')",
            (),
        )
        .await
        .expect("insert topic");
        conn.execute(
            "INSERT INTO subtopics VALUES ('newton','mechanics','Newton laws',1,'[]')",
            (),
        )
        .await
        .expect("insert subtopic");
        conn.execute(
            "INSERT INTO questions VALUES ('q1','JAMB','physics',2025,'past_paper','What is force?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"mass x accel\",\"inline\":[]}}]','a','newton',NULL,NULL,NULL,1.0,2,'h1')",
            (),
        )
        .await
        .expect("insert question");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        issue_key(
            &conn,
            "reports-only.secret",
            "commercial",
            "write:reports",
            false,
        )
        .await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    #[tokio::test]
    async fn subject_detail_is_keyed_and_scoped() {
        let app = seeded_app().await;

        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/subjects/JAMB/physics",
                None,
                None
            )
            .await
            .0,
            StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/subjects/JAMB/physics",
                Some("reports-only.secret"),
                None
            )
            .await
            .0,
            StatusCode::FORBIDDEN
        );

        let (status, v) = call(
            app.clone(),
            "GET",
            "/api/v1/subjects/JAMB/physics",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["slug"], "physics");
        assert_eq!(v["exam"], "JAMB");

        // A subject the exam never had is 404, not an empty body.
        assert_eq!(
            call(
                app,
                "GET",
                "/api/v1/subjects/JAMB/nope",
                Some("reader.secret"),
                None
            )
            .await
            .0,
            StatusCode::NOT_FOUND
        );
    }

    #[tokio::test]
    async fn syllabus_carries_the_tree_and_live_counts() {
        let app = seeded_app().await;
        let (status, v) = call(
            app.clone(),
            "GET",
            "/api/v1/subjects/JAMB/physics/syllabus",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["subject"]["slug"], "physics");
        assert_eq!(v["summary"]["topics"], 1);
        assert_eq!(v["summary"]["questions"], 1);
        assert_eq!(v["topics"][0]["slug"], "mechanics");
        assert_eq!(v["topics"][0]["question_count"], 1);
        assert_eq!(v["topics"][0]["objectives"][0], "state newton laws");
        assert_eq!(v["topics"][0]["subtopics"][0]["question_count"], 1);

        // Coverage is the same counts without the tree.
        let (status, c) = call(
            app,
            "GET",
            "/api/v1/subjects/JAMB/physics/coverage",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(c["summary"]["questions"], 1);
        assert!(c.get("topics").is_none(), "coverage serves no tree");
    }
}
