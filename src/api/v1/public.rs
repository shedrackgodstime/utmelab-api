//! The keyless discovery surface.
//!
//! Everything else under `/api/v1` is a keyed product surface. These two are
//! the shop window: they exist so a visitor can see what the bank holds before
//! they have a key, and they are coarse by construction: exam and subject
//! identity plus counts, never a row.
//!
//! The divide is structural, not stylistic. `api::router` mounts this router
//! without `verify_key`, and the `routes` tests sweep both halves: every keyed
//! route must refuse an anonymous caller, and these must answer one. A public
//! route is therefore a deliberate addition to an inventory, never a gate
//! somebody forgot.
//!
//! They are still metered. With no key there is no quota to bill, so the
//! caller's IP is the only identity available, and `middleware::public_limit`
//! caps it there.

use axum::{
    extract::{Path, Query, State},
    routing::get,
    Json, Router,
};

use crate::{
    api::v1::subjects::SyllabusQuery,
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

#[utoipa::path(
    get,
    path = "/api/v1/public/summary",
    tag = "public",
    operation_id = "publicSummary",
    summary = "How much the bank holds. No key required.",
    security(()),
    responses((status = 200, body = core::models::PublicSummary)),
)]
pub async fn summary(
    State(s): State<DbState>,
) -> Result<Json<core::models::PublicSummary>, AppError> {
    Ok(Json(store::catalog::public_summary(&s).await?))
}

#[utoipa::path(
    get,
    path = "/api/v1/public/exams",
    tag = "public",
    operation_id = "publicExams",
    summary = "Every exam with its subjects and sizes. No key required.",
    security(()),
    responses((status = 200, body = [core::models::PublicExam])),
)]
pub async fn exams(
    State(s): State<DbState>,
) -> Result<Json<Vec<core::models::PublicExam>>, AppError> {
    Ok(Json(store::catalog::public_exams(&s).await?))
}

#[utoipa::path(
    get,
    path = "/api/v1/public/syllabus/{exam}/{slug}",
    tag = "public",
    operation_id = "publicSyllabus",
    summary = "A subject's syllabus tree with live counts. No key required.",
    security(()),
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `JAMB`."),
        ("slug" = String, Path, description = "Subject slug, e.g. `physics`."),
        SyllabusQuery,
    ),
    responses(
        (status = 200, body = core::models::Syllabus),
        (status = 404, description = "No such subject in this exam"),
    ),
)]
pub async fn syllabus(
    State(s): State<DbState>,
    Path((exam, slug)): Path<(String, String)>,
    Query(f): Query<SyllabusQuery>,
) -> Result<Json<core::models::Syllabus>, AppError> {
    let Some(subject) = store::catalog::get_subject(&s, &exam, &slug).await? else {
        return Err(AppError::NotFound);
    };
    let tree = store::catalog::list_syllabus(&s, &exam, &slug).await?;
    let rows = store::catalog::subject_rows(&s, &exam, &slug, f.country.as_deref()).await?;
    Ok(Json(core::catalog::assemble_syllabus(
        &exam,
        subject,
        &tree,
        &rows,
        f.country.as_deref(),
    )))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/public/summary", get(summary))
        .route("/v1/public/exams", get(exams))
        .route("/v1/public/syllabus/{exam}/{slug}", get(syllabus))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::testing::{api_schema, bank_schema, call, connect, replica, state};

    /// The sorted field names of one JSON object.
    fn keys(value: &serde_json::Value) -> Vec<&str> {
        let mut out: Vec<&str> = value
            .as_object()
            .expect("an object")
            .keys()
            .map(String::as_str)
            .collect();
        out.sort_unstable();
        out
    }

    /// The bank tables this surface reads, one exam, two subjects (one of them
    /// empty), and two questions in the same subject of which exactly one is
    /// verified under the D62 rule.
    async fn seeded() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &[
                "exams",
                "subjects",
                "questions",
                "verifications",
                "topics",
                "subtopics",
                "topic_countries",
            ],
        )
        .await;
        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','Joint Admissions','[\"NG\"]','live',1,4,120,'[]')",
            (),
        )
        .await
        .expect("insert exam");
        conn.execute(
            "INSERT INTO subjects VALUES ('use-of-english','JAMB','Use of English',1,60)",
            (),
        )
        .await
        .expect("insert subject");
        conn.execute(
            "INSERT INTO subjects VALUES ('mathematics','JAMB','Mathematics',0,40)",
            (),
        )
        .await
        .expect("insert empty subject");
        conn.execute(
            "INSERT INTO questions VALUES ('q1','JAMB','use-of-english',2025,'authored','What is 3+3?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"6\",\"inline\":[]}}]','a','algebra',NULL,NULL,NULL,2.0,3,'h1')",
            (),
        )
        .await
        .expect("insert q1");
        conn.execute(
            "INSERT INTO questions VALUES ('q2','JAMB','use-of-english',2025,'authored','What is 4+4?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"8\",\"inline\":[]}}]','a','algebra',NULL,NULL,NULL,2.0,3,'h2')",
            (),
        )
        .await
        .expect("insert q2");
        // q1 is verified; q2 has no verification at all.
        conn.execute(
            "INSERT INTO verifications VALUES ('v1','q1','human','pass','[\"answer\",\"explanation\"]','review',NULL,'h1','2026-01-01T00:00:00Z')",
            (),
        )
        .await
        .expect("insert verification");
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// The figures a landing page shows have to be the figures a customer can
    /// read. Counting held rows as verified would overstate the product;
    /// dropping held would understate the bank and contradict the copy. Both
    /// numbers, each agreeing with a real read.
    #[tokio::test]
    async fn the_summary_separates_held_from_verified() {
        let app = seeded().await;
        let (status, body) = call(app, "GET", "/api/v1/public/summary", None, None).await;
        assert_eq!(status, axum::http::StatusCode::OK);
        assert_eq!(body["held"], 2, "both rows are on file");
        assert_eq!(body["verified"], 1, "only q1 passed its verification");
        assert_eq!(body["exams"], 1);
        assert_eq!(
            body["subjects"], 2,
            "a subject with no rows is still listed"
        );
    }

    /// Coarseness made mechanical: the payload is a fixed set of fields, so a
    /// content field cannot arrive by accident. A deliberate addition has to
    /// update this list, which is the point at which someone asks whether it
    /// belongs on a keyless surface.
    #[tokio::test]
    async fn the_payload_is_identity_and_counts_only() {
        let app = seeded().await;
        let (status, body) = call(app, "GET", "/api/v1/public/exams", None, None).await;
        assert_eq!(status, axum::http::StatusCode::OK);
        assert_eq!(body[0]["code"], "JAMB");
        assert_eq!(
            keys(&body[0]),
            [
                "code",
                "countries",
                "duration_minutes",
                "held",
                "name",
                "status",
                "subjects",
                "verified"
            ]
        );
        let subjects = body[0]["subjects"].as_array().expect("a subject list");
        assert_eq!(subjects.len(), 2);
        assert_eq!(
            keys(&subjects[0]),
            [
                "held",
                "is_compulsory",
                "name",
                "objective_paper_questions",
                "slug",
                "verified"
            ]
        );
        assert_eq!(body[0]["held"], 2);
        assert_eq!(body[0]["verified"], 1);
    }

    #[tokio::test]
    async fn the_public_syllabus_is_accessible_without_a_key() {
        let app = seeded().await;
        let (status, body) = call(
            app,
            "GET",
            "/api/v1/public/syllabus/JAMB/use-of-english",
            None,
            None,
        )
        .await;
        assert_eq!(status, axum::http::StatusCode::OK);
        assert_eq!(body["exam"], "JAMB");
        assert_eq!(body["subject"]["slug"], "use-of-english");
    }
}
