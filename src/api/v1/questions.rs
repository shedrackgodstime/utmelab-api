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

#[derive(Deserialize, utoipa::IntoParams)]
pub struct Detail {
    /// Include the answer and the working. Default: false.
    pub include_explanation: Option<bool>,
    /// Include the associated stimulus passage if present. Default: false.
    pub include_passage: Option<bool>,
}

#[utoipa::path(
    get,
    path = "/api/v1/questions/{id}",
    tag = "questions",
    operation_id = "getQuestion",
    summary = "One rendered question. The answer and working are withheld unless asked for.",
    params(
        ("id" = String, Path, description = "Question id."),
        Detail,
    ),
    responses(
        (status = 200, body = core::models::RenderedQuestion),
        (status = 404, description = "No such question"),
    ),
)]
pub async fn one(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
    Query(f): Query<Detail>,
) -> Result<Json<core::models::RenderedQuestion>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match store::catalog::get_question(&s, &id).await? {
        Some(q) => {
            let mut rendered = core::catalog::render(
                &q,
                f.include_explanation.unwrap_or(false),
                s.media_base_url.as_ref(),
            );
            if f.include_passage.unwrap_or(false) {
                if let Some(ref pid) = q.passage_id {
                    if let Some(mut passage) = store::catalog::get_passage(&s, pid).await? {
                        core::catalog::resolve_rich_text(
                            &mut passage.text,
                            s.media_base_url.as_ref(),
                        );
                        rendered.passage = Some(passage);
                    }
                }
            }
            Ok(Json(rendered))
        }
        None => Err(AppError::NotFound),
    }
}

#[derive(Deserialize, utoipa::IntoParams)]
pub struct List {
    /// Drill by topic slug.
    pub topic: Option<String>,
    /// Drill one subtopic id.
    pub subtopic: Option<String>,
    /// Scope to an exam.
    pub exam: Option<String>,
    /// Scope to a subject within that exam.
    pub subject: Option<String>,
    /// Only human-checked questions. Default: no filter.
    pub verified: Option<bool>,
    /// Scope to one cohort year.
    pub year: Option<u16>,
    /// Scope to a provenance, e.g. `past_paper`.
    pub source: Option<String>,
    /// Substring search over the question text.
    pub q: Option<String>,
    /// Scope to a country; a question with no stated scope survives any.
    pub country: Option<String>,
    /// Include the answer and the working. Default: false.
    pub include_explanation: Option<bool>,
    /// Include companion passages for questions referencing them. Default: false.
    pub include_passage: Option<bool>,
    /// 1-based page. Default: 1.
    pub page: Option<u32>,
    /// Rows per page, clamped. Default: 50, cap: 200.
    pub per_page: Option<u32>,
}

#[utoipa::path(
    get,
    path = "/api/v1/questions",
    tag = "questions",
    operation_id = "listQuestions",
    summary = "Questions, filtered and paged. The answer is withheld unless asked for.",
    params(List),
    responses(
        (status = 200, body = core::models::Page<core::models::RenderedQuestion>),
        (status = 404, description = "A filter naming a subject the bank never had"),
    ),
)]
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
        topic: f.topic.clone(),
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

    let passages = if f.include_passage.unwrap_or(false) {
        let pids: Vec<String> = questions
            .iter()
            .filter_map(|q| q.passage_id.clone())
            .collect();
        if !pids.is_empty() {
            let mut map = store::catalog::get_passages(&s, &pids).await?;
            for p in map.values_mut() {
                core::catalog::resolve_rich_text(&mut p.text, s.media_base_url.as_ref());
            }
            map
        } else {
            std::collections::HashMap::new()
        }
    } else {
        std::collections::HashMap::new()
    };

    let rendered: Vec<core::models::RenderedQuestion> = questions
        .iter()
        .map(|q| {
            let mut r = core::catalog::render(
                q,
                with_explanation,
                s.media_base_url.as_ref(),
            );
            if f.include_passage.unwrap_or(false) {
                if let Some(ref pid) = q.passage_id {
                    r.passage = passages.get(pid).cloned();
                }
            }
            r
        })
        .collect();

    Ok(Json(
        core::models::Page::new(
            rendered,
            page,
            per_page,
            total_records,
            with_explanation,
        )
        .with_passages(passages),
    ))
}

#[derive(Deserialize, utoipa::IntoParams)]
pub struct SampleParams {
    /// Scope to an exam (e.g. `JAMB`).
    pub exam: String,
    /// Scope to a subject slug (e.g. `physics`).
    pub subject: String,
    /// Number of questions to draw. Clamped to 1..50. Default: 15.
    pub count: Option<u32>,
    /// Optional deterministic seed for 1-on-1 challenges or reproducible tests.
    pub seed: Option<u64>,
    /// Only verified questions. Default: true.
    pub verified: Option<bool>,
    /// Optional drill to a specific topic slug.
    pub topic: Option<String>,
    /// Optional drill to a specific subtopic.
    pub subtopic: Option<String>,
    /// Scope to a cohort year.
    pub year: Option<u16>,
    /// Scope to a country; a question with no stated scope survives any.
    pub country: Option<String>,
    /// Include the answer and the working. Default: false.
    pub include_explanation: Option<bool>,
    /// Include companion passages for questions referencing them. Default: false.
    pub include_passage: Option<bool>,
}

#[utoipa::path(
    get,
    path = "/api/v1/questions/sample",
    tag = "questions",
    operation_id = "sampleQuestions",
    summary = "Sample a random or seeded subset of questions for quick quiz flows.",
    params(SampleParams),
    responses(
        (status = 200, body = core::models::SampledQuestions),
        (status = 404, description = "A subject the bank never had"),
    ),
)]
pub async fn sample(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Query(f): Query<SampleParams>,
) -> Result<Json<core::models::SampledQuestions>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    if !store::catalog::subject_exists(&s, &f.exam, &f.subject).await? {
        return Err(AppError::NotFound);
    }
    let rows = store::catalog::subject_rows(&s, &f.exam, &f.subject, f.country.as_deref()).await?;
    let verified_only = f.verified.unwrap_or(true);

    let topic_subtopics: Option<std::collections::HashSet<String>> = if let Some(ref top) = f.topic {
        let tree = store::catalog::list_syllabus(&s, &f.exam, &f.subject).await?;
        let subs: std::collections::HashSet<String> = tree
            .into_iter()
            .filter(|t| t.slug == *top)
            .flat_map(|t| t.subtopics.into_iter().map(|st| st.slug))
            .collect();
        Some(subs)
    } else {
        None
    };

    let mut candidates: Vec<core::models::Question> = rows
        .into_iter()
        .filter(|q| {
            if verified_only && !q.verified {
                return false;
            }
            if let Some(ref st) = f.subtopic {
                if q.subtopic_id.as_deref() != Some(st.as_str()) {
                    return false;
                }
            }
            if let Some(ref subs) = topic_subtopics {
                if !q.subtopic_id.as_deref().map(|id| subs.contains(id)).unwrap_or(false) {
                    return false;
                }
            }
            if let Some(year) = f.year {
                if q.year != year {
                    return false;
                }
            }
            true
        })
        .collect();

    let total_available = candidates.len();
    use rand::seq::SliceRandom;
    use rand::SeedableRng;
    let seed = f.seed.unwrap_or_else(rand::random);
    let mut rng = rand::rngs::StdRng::seed_from_u64(seed);
    candidates.shuffle(&mut rng);

    let count = f.count.unwrap_or(15).clamp(1, 50) as usize;
    candidates.truncate(count);

    let with_explanation = f.include_explanation.unwrap_or(false);

    let passages = if f.include_passage.unwrap_or(false) {
        let pids: Vec<String> = candidates
            .iter()
            .filter_map(|q| q.passage_id.clone())
            .collect();
        if !pids.is_empty() {
            let mut map = store::catalog::get_passages(&s, &pids).await?;
            for p in map.values_mut() {
                core::catalog::resolve_rich_text(&mut p.text, s.media_base_url.as_ref());
            }
            Some(map)
        } else {
            None
        }
    } else {
        None
    };

    let rendered: Vec<core::models::RenderedQuestion> = candidates
        .iter()
        .map(|q| {
            let mut r = core::catalog::render(
                q,
                with_explanation,
                s.media_base_url.as_ref(),
            );
            if let Some(ref map) = passages {
                if let Some(ref pid) = q.passage_id {
                    r.passage = map.get(pid).cloned();
                }
            }
            r
        })
        .collect();

    Ok(Json(core::models::SampledQuestions {
        exam: f.exam,
        subject: f.subject,
        count: rendered.len(),
        total_available,
        questions: rendered,
        passages,
    }))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/questions", get(list))
        .route("/v1/questions/sample", get(sample))
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
            &["subjects", "questions", "verifications", "subtopics", "topic_countries", "passages"],
        )
        .await;
        conn.execute(
            "INSERT INTO subjects VALUES ('physics','JAMB','Physics',0,40)",
            (),
        )
        .await
        .expect("insert subject");
        conn.execute(
            "INSERT INTO passages VALUES ('p1','JAMB','physics',2025,'comprehension','Passage 1','Author','Passage content','[]')",
            (),
        )
        .await
        .expect("insert passage");
        conn.execute(
            "INSERT INTO questions VALUES ('q1','JAMB','physics',2025,'past_paper','What is 2+2?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"4\",\"inline\":[]}}]','a',NULL,NULL,'p1','{\"key_point\":{\"text\":\"addition\",\"inline\":[]},\"body\":{\"text\":\"2+2=4\",\"inline\":[]}}',1.0,2,'h1')",
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

    #[tokio::test]
    async fn questions_page_includes_companion_passages_on_request() {
        let app = seeded_app().await;
        let (status, v) = call(
            app.clone(),
            "GET",
            "/api/v1/questions?include_passage=true",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert!(v.get("passages").is_some());
        assert_eq!(v["passages"]["p1"]["title"], "Passage 1");
        assert_eq!(v["questions"][0]["passage"]["title"], "Passage 1");

        let (status_one, v_one) = call(
            app,
            "GET",
            "/api/v1/questions/q1?include_passage=true",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status_one, StatusCode::OK);
        assert!(v_one.get("passage").is_some());
        assert_eq!(v_one["passage"]["id"], "p1");
    }

    #[tokio::test]
    async fn questions_sample_draws_seeded_set() {
        let app = seeded_app().await;

        let (status, v) = call(
            app.clone(),
            "GET",
            "/api/v1/questions/sample?exam=JAMB&subject=physics&count=5&seed=42&include_passage=true&year=2025",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["exam"], "JAMB");
        assert_eq!(v["subject"], "physics");
        assert_eq!(v["count"], 1);
        assert_eq!(v["total_available"], 1);
        assert_eq!(v["questions"][0]["id"], "q1");
        assert!(v.get("passages").is_some());
        assert_eq!(v["passages"]["p1"]["title"], "Passage 1");
        assert_eq!(v["questions"][0]["passage"]["title"], "Passage 1");

        // Filter by non-matching year
        let (status_yr, v_yr) = call(
            app.clone(),
            "GET",
            "/api/v1/questions/sample?exam=JAMB&subject=physics&year=2010",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status_yr, StatusCode::OK);
        assert_eq!(v_yr["count"], 0);

        // Absent subject returns 404
        let (status_404, _) = call(
            app,
            "GET",
            "/api/v1/questions/sample?exam=JAMB&subject=nonexistent",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status_404, StatusCode::NOT_FOUND);
    }
}
