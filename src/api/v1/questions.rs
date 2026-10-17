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
        verified: f.verified,
    };
    let with_explanation = f.include_explanation.unwrap_or(false);
    let (page, per_page) =
        core::catalog::page_bounds(f.page.unwrap_or(1), f.per_page.unwrap_or(50));
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
    use crate::state::AppState;
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    /// Offline replica seeded through a raw connection. This is the
    /// reference for a keyed handler test: prove the identity extractor,
    /// the scope check, the store call, and the page envelope through the
    /// real router, not the handler in isolation.
    async fn seeded_state() -> AppState {
        let path = std::env::temp_dir().join(format!(
            "utmelab-questions-api-test-{}-{}.db",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        let db = turso::sync::Builder::new_remote(path.to_str().expect("tmp path"))
            .with_auth_token("test-only")
            .bootstrap_if_empty(false)
            .build()
            .await
            .expect("local sync db builds offline");
        let conn = db.connect().await.expect("connect");
        for ddl in [
            "CREATE TABLE api_keys (prefix TEXT PRIMARY KEY, hash TEXT NOT NULL, tier TEXT NOT NULL DEFAULT 'commercial', scopes TEXT NOT NULL DEFAULT 'read:catalog', revoked INTEGER NOT NULL DEFAULT 0, owner TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE questions (id TEXT, exam TEXT, subject TEXT, year INTEGER, source TEXT, text TEXT, inline TEXT, options TEXT, answer TEXT, subtopic_id TEXT, section TEXT, passage_id TEXT, explanation TEXT, marks REAL, difficulty INTEGER, content_hash TEXT)",
            "CREATE TABLE verifications (id TEXT, question_id TEXT, kind TEXT, verdict TEXT, scope TEXT, verifier TEXT, detail TEXT, content_hash TEXT, created_at TEXT)",
        ] {
            conn.execute(ddl, ()).await.expect("create table");
        }
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
        for (prefix, secret, scopes, revoked) in [
            ("reader", "secret", "read:catalog", 0),
            ("reports-only", "secret", "write:reports", 0),
            ("revoked", "secret", "read:catalog", 1),
        ] {
            let full = format!("{prefix}.{secret}");
            conn.execute(
                "INSERT INTO api_keys (prefix, hash, tier, scopes, revoked, owner) VALUES (?1, ?2, 'commercial', ?3, ?4, '')",
                vec![
                    turso::Value::Text(prefix.to_string()),
                    turso::Value::Text(crate::core::hex::encode(&{
                        use sha2::Digest;
                        sha2::Sha256::digest(full.as_bytes())
                    })),
                    turso::Value::Text(scopes.to_string()),
                    turso::Value::Integer(revoked),
                ],
            )
            .await
            .expect("insert key");
        }
        let d = crate::state::DbState::detached(std::sync::Arc::new(db));
        AppState {
            name: std::sync::Arc::from("test"),
            db: d.db,
            db_gate: d.db_gate,
            conns: d.conns,
            metrics: d.metrics,
            cookie_secure: false,
            write_mutex: d.write_mutex,
            contract_ok: d.contract_ok,
            limiter: d.limiter,
        }
    }

    async fn get(
        app: axum::Router,
        uri: &str,
        key: Option<&str>,
    ) -> (StatusCode, serde_json::Value) {
        let mut req = Request::builder().uri(uri);
        if let Some(k) = key {
            req = req.header("x-api-key", k);
        }
        let res = app
            .oneshot(req.body(Body::empty()).expect("request"))
            .await
            .expect("call");
        let status = res.status();
        let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
            .await
            .expect("body");
        let value = serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null);
        (status, value)
    }

    fn app(state: AppState) -> axum::Router {
        crate::routes::router(state, &crate::config::Config::default())
    }

    #[tokio::test]
    async fn questions_read_is_keyed_scoped_and_paged() {
        let app = app(seeded_state().await);

        // No key: the extractor rejects before the handler runs.
        assert_eq!(
            get(app.clone(), "/api/v1/questions", None).await.0,
            StatusCode::UNAUTHORIZED
        );
        // Authenticated, but without `read:catalog`: forbidden, not 401.
        assert_eq!(
            get(
                app.clone(),
                "/api/v1/questions",
                Some("reports-only.secret")
            )
            .await
            .0,
            StatusCode::FORBIDDEN
        );
        // A revoked key never gets in.
        assert_eq!(
            get(app.clone(), "/api/v1/questions", Some("revoked.secret"))
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );

        // A live key gets the shared page envelope, answer withheld.
        let (status, v) = get(app, "/api/v1/questions", Some("reader.secret")).await;
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
    }

    #[tokio::test]
    async fn questions_page_clamps_and_reveals_on_request() {
        let app = app(seeded_state().await);
        let (status, v) = get(
            app,
            "/api/v1/questions?per_page=0&include_explanation=true",
            Some("reader.secret"),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["per_page"], 1, "per_page clamps to at least one");
        assert_eq!(v["includes_explanation"], true);
        assert_eq!(v["questions"][0]["answer"], "a");
    }
}
