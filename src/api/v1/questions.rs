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
        verified: f.verified,
        country: f.country.clone(),
    };
    let with_explanation = f.include_explanation.unwrap_or(false);
    let (page, per_page) = core::catalog::page_query(f.page, f.per_page);
    let (questions, total_records) =
        store::catalog::list_questions(&s, &filter, page, per_page).await?;
    let rendered = questions
        .iter()
        .map(|q| core::catalog::render(q, with_explanation))
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
        .route("/v1/questions", get(list))
        .route("/v1/questions/{id}", get(one))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::testing::{api_schema, bank_schema, call, connect, issue_key, replica, state};
    use axum::http::StatusCode;

    /// Offline replica seeded through a raw connection. This is the reference
    /// for a keyed handler test: prove the identity extractor, the scope check,
    /// the store call, and the page envelope through the real router, not the
    /// handler in isolation.
    async fn seeded_app() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &["questions", "verifications", "subtopics", "topic_countries"],
        )
        .await;
        conn.execute(
            "INSERT INTO questions VALUES ('q1','JAMB','physics',2025,'past_paper','What is 2+2?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"4\",\"inline\":[]}}]','a',NULL,NULL,NULL,'{\"key_point\":{\"text\":\"addition\",\"inline\":[]},\"body\":{\"text\":\"2+2=4\",\"inline\":[]}}',1.0,2,'h1')",
            (),
        )
        .await
        .expect("insert question");
        conn.execute(
            "INSERT INTO verifications VALUES ('v1','q1','human','pass','[\"answer\",\"explanation\"]','review',NULL,'h1','2026-01-01T00:00:00Z')",
            (),
        )
        .await
        .expect("insert verification");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        issue_key(
            &conn,
            "reports-only.secret",
            "commercial",
            "write:reports",
            false,
        )
        .await;
        issue_key(&conn, "revoked.secret", "commercial", "read:catalog", true).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    #[tokio::test]
    async fn questions_read_is_keyed_scoped_and_paged() {
        let app = seeded_app().await;

        // No key: the extractor rejects before the handler runs.
        assert_eq!(
            call(app.clone(), "GET", "/api/v1/questions", None, None)
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );
        // Authenticated, but without `read:catalog`: forbidden, not 401.
        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/questions",
                Some("reports-only.secret"),
                None
            )
            .await
            .0,
            StatusCode::FORBIDDEN
        );
        // A revoked key never gets in.
        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/questions",
                Some("revoked.secret"),
                None
            )
            .await
            .0,
            StatusCode::UNAUTHORIZED
        );

        // A live key gets the shared page envelope, answer withheld.
        let (status, v) = call(
            app.clone(),
            "GET",
            "/api/v1/questions",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["total_records"], 1);
        assert_eq!(v["total_pages"], 1);
        assert_eq!(v["page"], 1);
        assert_eq!(v["per_page"], 50);
        assert_eq!(v["includes_explanation"], false);
        assert_eq!(v["questions"].as_array().expect("array").len(), 1);
        assert_eq!(v["questions"][0]["id"], "q1");
        assert_eq!(v["questions"][0]["verified"], true);
        assert!(
            v["questions"][0].get("answer").is_none(),
            "answer must be withheld by default"
        );

        // The country filter is a scope filter, not a 400. q1 has no subtopic,
        // so it is universal and survives any country.
        let (status, scoped) = call(
            app,
            "GET",
            "/api/v1/questions?country=GH",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(scoped["total_records"], 1);
        assert_eq!(scoped["questions"][0]["id"], "q1");
    }

    #[tokio::test]
    async fn questions_page_clamps_and_reveals_on_request() {
        let app = seeded_app().await;
        let (status, v) = call(
            app,
            "GET",
            "/api/v1/questions?per_page=0&include_explanation=true",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["per_page"], 1, "per_page clamps to at least one");
        assert_eq!(v["includes_explanation"], true);
        assert_eq!(v["questions"][0]["answer"], "a");
    }
}
