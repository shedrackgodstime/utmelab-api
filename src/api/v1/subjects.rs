//! `/api/v1/subjects/{exam}/{slug}` — one subject, its syllabus, and its
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

pub async fn by_exam(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(exam): Path<String>,
) -> Result<Json<Vec<core::models::Subject>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(store::catalog::list_subjects(&s, &exam).await?))
}

/// One subject offering within an exam.
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

#[derive(Deserialize)]
pub struct SyllabusQuery {
    /// Country code filter, e.g. `GH`. Absent is the full honest tree.
    pub country: Option<String>,
}

/// Assemble one subject's tree. A subject the exam never had is 404, not an
/// empty tree.
async fn tree(
    s: &DbState,
    exam: &str,
    slug: &str,
    country: Option<&str>,
) -> Result<core::models::Syllabus, AppError> {
    let Some(subject) = store::catalog::get_subject(s, exam, slug).await? else {
        return Err(AppError::NotFound);
    };
    let tree = store::catalog::list_syllabus(s, exam, slug).await?;
    let rows = store::catalog::subject_rows(s, exam, slug, country).await?;
    Ok(core::catalog::assemble_syllabus(
        exam, subject, &tree, &rows, country,
    ))
}

/// The whole topic tree with live counts.
pub async fn syllabus(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, slug)): Path<(String, String)>,
    Query(f): Query<SyllabusQuery>,
) -> Result<Json<core::models::Syllabus>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(tree(&s, &exam, &slug, f.country.as_deref()).await?))
}

/// Coverage without the tree: counts only, for progress bars and checklists.
pub async fn coverage(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, slug)): Path<(String, String)>,
    Query(f): Query<SyllabusQuery>,
) -> Result<Json<core::models::Coverage>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let s = tree(&s, &exam, &slug, f.country.as_deref()).await?;
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
    use crate::state::AppState;
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    /// Offline replica seeded through a raw connection. Same harness as the
    /// questions handler test: the identity extractor, the scope check, the
    /// store reads, and the assembly, all through the real router.
    async fn seeded_state() -> AppState {
        let path = std::env::temp_dir().join(format!(
            "utmelab-subjects-api-test-{}-{}.db",
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
            "CREATE TABLE subjects (slug TEXT, exam TEXT, name TEXT, is_compulsory INTEGER, objective_paper_questions INTEGER)",
            "CREATE TABLE topics (slug TEXT, subject TEXT, exam TEXT, name TEXT, \"order\" INTEGER, weight INTEGER, objectives TEXT)",
            "CREATE TABLE subtopics (slug TEXT, topic TEXT, name TEXT, \"order\" INTEGER, objectives TEXT)",
            "CREATE TABLE topic_countries (topic TEXT NOT NULL, country TEXT NOT NULL, PRIMARY KEY (topic, country))",
            "CREATE TABLE questions (id TEXT, exam TEXT, subject TEXT, year INTEGER, source TEXT, text TEXT, inline TEXT, options TEXT, answer TEXT, subtopic_id TEXT, section TEXT, passage_id TEXT, explanation TEXT, marks REAL, difficulty INTEGER, content_hash TEXT)",
            "CREATE TABLE verifications (id TEXT, question_id TEXT, kind TEXT, verdict TEXT, scope TEXT, verifier TEXT, detail TEXT, content_hash TEXT, created_at TEXT)",
        ] {
            conn.execute(ddl, ()).await.expect("create table");
        }
        conn.execute(
            "INSERT INTO subjects VALUES ('physics','JAMB','Physics',0,40)",
            (),
        )
        .await
        .expect("insert subject");
        conn.execute(
            "INSERT INTO topics VALUES ('mechanics','physics','JAMB','Mechanics',1,0,'[\"state newton laws\"]')",
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
        for (prefix, scopes, revoked) in [
            ("reader", "read:catalog", 0),
            ("reports-only", "write:reports", 0),
        ] {
            let full = format!("{prefix}.secret");
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
    async fn subject_detail_is_keyed_and_scoped() {
        let app = app(seeded_state().await);

        assert_eq!(
            get(app.clone(), "/api/v1/subjects/JAMB/physics", None)
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            get(
                app.clone(),
                "/api/v1/subjects/JAMB/physics",
                Some("reports-only.secret")
            )
            .await
            .0,
            StatusCode::FORBIDDEN
        );

        let (status, v) = get(
            app.clone(),
            "/api/v1/subjects/JAMB/physics",
            Some("reader.secret"),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["slug"], "physics");
        assert_eq!(v["exam"], "JAMB");

        // A subject the exam never had is 404, not an empty body.
        assert_eq!(
            get(app, "/api/v1/subjects/JAMB/nope", Some("reader.secret"))
                .await
                .0,
            StatusCode::NOT_FOUND
        );
    }

    #[tokio::test]
    async fn syllabus_carries_the_tree_and_live_counts() {
        let app = app(seeded_state().await);
        let (status, v) = get(
            app.clone(),
            "/api/v1/subjects/JAMB/physics/syllabus",
            Some("reader.secret"),
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
        let (status, c) = get(
            app,
            "/api/v1/subjects/JAMB/physics/coverage",
            Some("reader.secret"),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(c["summary"]["questions"], 1);
        assert!(c.get("topics").is_none(), "coverage serves no tree");
    }
}
