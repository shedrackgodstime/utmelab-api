//! `GET /v1/exams/{exam}/papers`: how an exam is shaped, and whether the
//! bank can fill it. Read-only.
//!
//! The scheme is a constant restated from the bank (D19): subject counts,
//! duration, rules, and requirement groups all come from content rather
//! than a second copy, so it changes only when the bank does. Readiness is
//! kept beside the scheme, and completeness is only ever claimed for a
//! country scope.
//!
//! `POST /v1/papers/{exam}/{subject}` assembles one subject's mock from the
//! rows the bank holds (D69/D70): deterministic per seed, answers always
//! withheld, 409 naming the gaps until the bank can fill the paper.
//! `.../score` re-assembles with the same seed and marks only submitted
//! ids: stateless, no paper table, no stored attempts.

use std::collections::HashMap;

use axum::{
    extract::{Path, Query, State},
    routing::{get, post},
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
pub struct PapersQuery {
    /// Country scope, e.g. `GH`. A one-country exam implies its own;
    /// anything else needs it said out loud, and completeness is only
    /// ever claimed for a scope.
    pub country: Option<String>,
}

#[derive(Deserialize, utoipa::IntoParams)]
pub struct AssembleQuery {
    /// Deterministic draw. Same seed, same paper. Defaults to 1, as the
    /// published contract always has: omitting it stays reproducible.
    pub seed: Option<u64>,
    /// Country scope. No row is restricted to a country today
    /// (`topic_countries` is empty), so this does not change the draw; it
    /// is accepted so the request is the same shape as readiness.
    pub country: Option<String>,
    /// Include answers and explanations. Default: false.
    pub include_explanation: Option<bool>,
    /// Include companion passages for reading comprehension items. Default: false.
    pub include_passage: Option<bool>,
}

#[derive(Deserialize, utoipa::ToSchema)]
pub struct ScoreRequest {
    pub seed: u64,
    pub country: Option<String>,
    #[serde(default)]
    pub answers: HashMap<String, String>,
    /// Include answers and explanations with the score. Default: false.
    #[serde(default)]
    pub include_explanation: Option<bool>,
}

#[derive(serde::Serialize, utoipa::ToSchema)]
pub struct PaperSectionOut {
    pub topic: String,
    pub name: String,
    pub questions: Vec<core::models::RenderedQuestion>,
}

#[derive(serde::Serialize, utoipa::ToSchema)]
pub struct AssembledPaperOut {
    pub exam: String,
    pub subject: String,
    pub seed: u64,
    pub mode: core::papers::PaperMode,
    pub total: usize,
    pub sections: Vec<PaperSectionOut>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub passages: Option<HashMap<String, core::models::Passage>>,
}

#[derive(serde::Serialize, utoipa::ToSchema)]
pub struct ScoredQuestion {
    pub id: String,
    pub submitted: Option<String>,
    pub correct: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub answer: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub explanation: Option<core::models::Explanation>,
}

#[derive(serde::Serialize, utoipa::ToSchema)]
pub struct ScoredPaper {
    pub exam: String,
    pub subject: String,
    pub seed: u64,
    pub score: usize,
    pub total: usize,
    pub questions: Vec<ScoredQuestion>,
}

#[utoipa::path(
    get,
    path = "/api/v1/exams/{exam}/papers",
    tag = "papers",
    operation_id = "getExamReadiness",
    summary = "How an exam's paper is shaped, and whether the bank can fill it.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `JAMB`."),
        PapersQuery,
    ),
    responses(
        (status = 200, body = core::models::PaperReadiness),
        (status = 404, description = "No such exam, or an exam with no subjects"),
    ),
)]
pub async fn readiness(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(exam): Path<String>,
    Query(f): Query<PapersQuery>,
) -> Result<Json<core::models::PaperReadiness>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let Some(record) = store::catalog::get_exam(&s, &exam).await? else {
        return Err(AppError::NotFound);
    };
    let subjects = store::catalog::list_subjects(&s, &exam).await?;
    if subjects.is_empty() {
        return Err(AppError::NotFound);
    }
    let country = core::papers::effective_country(&record, f.country.as_deref());
    let stats = store::catalog::subject_stats(&s, &exam, country.as_deref()).await?;
    let requirements = match country.as_deref() {
        Some(cc) => store::catalog::list_requirements(&s, &exam, cc).await?,
        None => Vec::new(),
    };
    let scheme = core::papers::build_scheme(&record, &subjects, &stats, country, requirements);
    let complete = core::papers::is_complete(&scheme);
    Ok(Json(core::models::PaperReadiness {
        exam: record.code.clone(),
        scheme,
        complete,
    }))
}

#[utoipa::path(
    post,
    path = "/api/v1/papers/{exam}/{subject}",
    tag = "papers",
    operation_id = "assemblePaper",
    summary = "Assemble one subject's mock. Deterministic per seed, answers withheld.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `JAMB`."),
        ("subject" = String, Path, description = "Subject slug, e.g. `physics`."),
        AssembleQuery,
    ),
    responses(
        (status = 200, body = AssembledPaperOut),
        (status = 404, description = "No such exam subject"),
        (status = 409, description = "The bank cannot fill this paper yet; the body names the gaps"),
    ),
)]
pub async fn assemble_paper(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject)): Path<(String, String)>,
    Query(f): Query<AssembleQuery>,
) -> Result<Json<AssembledPaperOut>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let seed = f.seed.unwrap_or(1);
    let paper = build(&s, &exam, &subject, seed, f.country.as_deref()).await?;
    let mut out = into_out(
        paper,
        f.include_explanation.unwrap_or(false),
        s.media_base_url.as_ref(),
    );
    if f.include_passage.unwrap_or(false) {
        let pids: Vec<String> = out
            .sections
            .iter()
            .flat_map(|sec| sec.questions.iter().filter_map(|q| q.passage_id.clone()))
            .collect();
        if !pids.is_empty() {
            let mut map = store::catalog::get_passages(&s, &pids).await?;
            for p in map.values_mut() {
                core::catalog::resolve_rich_text(&mut p.text, s.media_base_url.as_ref());
            }
            for sec in &mut out.sections {
                for q in &mut sec.questions {
                    if let Some(ref pid) = q.passage_id {
                        q.passage = map.get(pid).cloned();
                    }
                }
            }
            out.passages = Some(map);
        }
    }
    Ok(Json(out))
}

/// Score re-assembles the same paper with the same seed, then marks only
/// submitted ids. Correctness is never revealed for a guess not made.
#[utoipa::path(
    post,
    path = "/api/v1/papers/{exam}/{subject}/score",
    tag = "papers",
    operation_id = "scorePaper",
    summary = "Re-assemble the same paper and mark the submitted ids. Stateless.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `JAMB`."),
        ("subject" = String, Path, description = "Subject slug, e.g. `physics`."),
    ),
    responses(
        (status = 200, body = ScoredPaper),
        (status = 404, description = "No such exam subject"),
        (status = 409, description = "The bank cannot fill this paper yet"),
    ),
)]
pub async fn score_paper(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject)): Path<(String, String)>,
    Json(body): Json<ScoreRequest>,
) -> Result<Json<ScoredPaper>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let paper = build(&s, &exam, &subject, body.seed, body.country.as_deref()).await?;
    let total = paper.total();
    let (score, marked) = core::papers::mark(&paper, &body.answers);
    let with_explanation = body.include_explanation.unwrap_or(false);

    let q_map: HashMap<String, &core::models::Question> = if with_explanation {
        paper
            .sections
            .iter()
            .flat_map(|sec| sec.questions.iter().map(|q| (q.id.clone(), q)))
            .collect()
    } else {
        HashMap::new()
    };

    Ok(Json(ScoredPaper {
        exam: paper.exam,
        subject: paper.subject,
        seed: paper.seed,
        score,
        total,
        questions: marked
            .into_iter()
            .map(|m| {
                let (answer, explanation) = if with_explanation {
                    if let Some(q) = q_map.get(&m.id) {
                        let mut exp = q.explanation.clone();
                        if let Some(ref mut e) = exp {
                            core::catalog::resolve_rich_text(
                                &mut e.key_point,
                                s.media_base_url.as_ref(),
                            );
                            core::catalog::resolve_rich_text(
                                &mut e.body,
                                s.media_base_url.as_ref(),
                            );
                            if let Some(ref mut trap) = e.trap {
                                core::catalog::resolve_rich_text(
                                    trap,
                                    s.media_base_url.as_ref(),
                                );
                            }
                        }
                        (Some(q.answer.clone()), exp)
                    } else {
                        (None, None)
                    }
                } else {
                    (None, None)
                };
                ScoredQuestion {
                    id: m.id,
                    submitted: m.submitted,
                    correct: m.correct,
                    answer,
                    explanation,
                }
            })
            .collect(),
    }))
}

/// Fetch the bank for one subject and assemble by the gate it earns. The
/// 404 names an exam/subject the bank never had; the 409 names a paper the
/// bank cannot fill yet.
async fn build(
    s: &DbState,
    exam: &str,
    subject: &str,
    seed: u64,
    country: Option<&str>,
) -> Result<core::papers::AssembledPaper, AppError> {
    let Some(record) = store::catalog::get_subject(s, exam, subject).await? else {
        return Err(AppError::NotFound);
    };
    let blueprints = store::catalog::list_blueprints(s, exam, subject).await?;
    let syllabus = store::catalog::list_syllabus(s, exam, subject).await?;
    let rows = store::catalog::subject_rows(s, exam, subject, country).await?;
    let bank = core::papers::SubjectBank {
        subject: record,
        blueprints,
        syllabus,
        rows,
    };
    core::papers::assemble(&bank, seed).map_err(|u| AppError::Conflict(u.detail()))
}

fn into_out(
    paper: core::papers::AssembledPaper,
    include_explanation: bool,
    media_base_url: &str,
) -> AssembledPaperOut {
    let total = paper.total();
    AssembledPaperOut {
        exam: paper.exam,
        subject: paper.subject,
        seed: paper.seed,
        mode: paper.mode,
        total,
        sections: paper
            .sections
            .into_iter()
            .map(|sec| PaperSectionOut {
                topic: sec.topic,
                name: sec.name,
                questions: sec
                    .questions
                    .iter()
                    .map(|q| core::catalog::render(q, include_explanation, media_base_url))
                    .collect(),
            })
            .collect(),
        passages: None,
    }
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/exams/{exam}/papers", get(readiness))
        .route("/v1/papers/{exam}/{subject}", post(assemble_paper))
        .route("/v1/papers/{exam}/{subject}/score", post(score_paper))
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
        bank_schema(
            &conn,
            &[
                "exams",
                "subjects",
                "exam_requirements",
                "questions",
                "verifications",
                "topics",
                "subtopics",
                "topic_countries",
                "passages",
                "blueprints",
            ],
        )
        .await;
        conn.execute(
            "INSERT INTO passages VALUES ('p1','JAMB','math',2025,'comprehension','Math Passage','Author','Body','[]')",
            (),
        )
        .await
        .expect("insert passage");
        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','Joint Admissions','[\"NG\"]','live',1,4,120,'[]')",
            (),
        )
        .await
        .expect("insert exam");
        conn.execute(
            "INSERT INTO subjects VALUES ('physics','JAMB','Physics',0,40)",
            (),
        )
        .await
        .expect("insert subject");
        conn.execute(
            "INSERT INTO subjects VALUES ('math','JAMB','Math',0,1)",
            (),
        )
        .await
        .expect("insert math subject");
        conn.execute(
            "INSERT INTO questions VALUES ('q1','JAMB','math',2025,'past_paper','What is 1+1?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"2\",\"inline\":[]}}]','a',NULL,NULL,'p1','{\"key_point\":{\"text\":\"k\",\"inline\":[]},\"body\":{\"text\":\"b\",\"inline\":[]}}',1.0,1,'h1')",
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
        conn.execute(
            "INSERT INTO exam_requirements VALUES ('JAMB','NG','sciences',1,'[\"physics\"]')",
            (),
        )
        .await
        .expect("insert requirement");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// The readiness view carries the scope it was computed for and the
    /// requirement set it judged, so a consumer can see what `complete` meant.
    #[tokio::test]
    async fn paper_readiness_is_keyed_and_scoped() {
        let app = seeded_app().await;

        assert_eq!(
            call(app.clone(), "GET", "/api/v1/exams/JAMB/papers", None, None)
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );

        let (status, v) = call(
            app.clone(),
            "GET",
            "/api/v1/exams/JAMB/papers",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "body: {v}");
        assert_eq!(v["exam"], "JAMB");
        assert_eq!(v["scheme"]["country"], "NG");
        assert_eq!(v["scheme"]["subjects"][0]["slug"], "physics");
        assert_eq!(v["scheme"]["requirements"][0]["min_select"], 1);
        assert_eq!(v["scheme"]["requirements"][0]["subjects"][0], "physics");
        // No verified questions are held, so no subject slot is ready yet.
        assert_eq!(v["complete"], false);

        assert_eq!(
            call(
                app,
                "GET",
                "/api/v1/exams/WAEC/papers",
                Some("reader.secret"),
                None
            )
            .await
            .0,
            StatusCode::NOT_FOUND
        );
    }

    #[tokio::test]
    async fn assemble_paper_includes_explanation_and_passages_on_request() {
        let app = seeded_app().await;

        let (status_default, v_default) = call(
            app.clone(),
            "POST",
            "/api/v1/papers/JAMB/math",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status_default, StatusCode::OK);
        assert_eq!(v_default["total"], 1);
        let q = &v_default["sections"][0]["questions"][0];
        assert!(q.get("answer").is_none());
        assert!(q.get("explanation").is_none());
        assert!(v_default.get("passages").is_none());

        let (status, v) = call(
            app,
            "POST",
            "/api/v1/papers/JAMB/math?include_explanation=true&include_passage=true",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let q_with = &v["sections"][0]["questions"][0];
        assert_eq!(q_with["answer"], "a");
        assert!(q_with.get("explanation").is_some());
        assert!(v.get("passages").is_some());
        assert_eq!(v["passages"]["p1"]["title"], "Math Passage");
        assert_eq!(q_with["passage"]["title"], "Math Passage");
    }

    #[tokio::test]
    async fn score_paper_includes_explanation_on_request() {
        let app = seeded_app().await;

        let score_req = serde_json::json!({
            "seed": 1,
            "answers": {
                "q1": "a"
            },
            "include_explanation": true
        });

        let (status, v) = call(
            app,
            "POST",
            "/api/v1/papers/JAMB/math/score",
            Some("reader.secret"),
            Some(&score_req.to_string()),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["score"], 1);
        let q = &v["questions"][0];
        assert_eq!(q["id"], "q1");
        assert_eq!(q["correct"], true);
        assert_eq!(q["answer"], "a");
        assert!(q.get("explanation").is_some());
    }
}
