//! `GET /v1/exams/{exam}/papers` — how an exam is shaped, and whether the
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
//! ids — stateless, no paper table, no stored attempts.

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

#[derive(Deserialize)]
pub struct PapersQuery {
    /// Country scope, e.g. `GH`. A one-country exam implies its own;
    /// anything else needs it said out loud, and completeness is only
    /// ever claimed for a scope.
    pub country: Option<String>,
}

#[derive(Deserialize)]
pub struct AssembleQuery {
    /// Deterministic draw. Same seed, same paper. Defaults to 1, as the
    /// published contract always has: omitting it stays reproducible.
    pub seed: Option<u64>,
    /// Country scope. No row is restricted to a country today
    /// (`topic_countries` is empty), so this does not change the draw; it
    /// is accepted so the request is the same shape as readiness.
    pub country: Option<String>,
}

#[derive(Deserialize)]
pub struct ScoreRequest {
    pub seed: u64,
    pub country: Option<String>,
    #[serde(default)]
    pub answers: HashMap<String, String>,
}

#[derive(serde::Serialize)]
pub struct PaperSectionOut {
    pub topic: String,
    pub name: String,
    pub questions: Vec<core::models::RenderedQuestion>,
}

#[derive(serde::Serialize)]
pub struct AssembledPaperOut {
    pub exam: String,
    pub subject: String,
    pub seed: u64,
    pub mode: core::papers::PaperMode,
    pub total: usize,
    pub sections: Vec<PaperSectionOut>,
}

#[derive(serde::Serialize)]
pub struct ScoredQuestion {
    pub id: String,
    pub submitted: Option<String>,
    pub correct: bool,
}

#[derive(serde::Serialize)]
pub struct ScoredPaper {
    pub exam: String,
    pub subject: String,
    pub seed: u64,
    pub score: usize,
    pub total: usize,
    pub questions: Vec<ScoredQuestion>,
}

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

pub async fn assemble_paper(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject)): Path<(String, String)>,
    Query(f): Query<AssembleQuery>,
) -> Result<Json<AssembledPaperOut>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let seed = f.seed.unwrap_or(1);
    let paper = build(&s, &exam, &subject, seed, f.country.as_deref()).await?;
    Ok(Json(into_out(paper)))
}

/// Score re-assembles the same paper with the same seed, then marks only
/// submitted ids. Correctness is never revealed for a guess not made.
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
    Ok(Json(ScoredPaper {
        exam: paper.exam,
        subject: paper.subject,
        seed: paper.seed,
        score,
        total,
        questions: marked
            .into_iter()
            .map(|m| ScoredQuestion {
                id: m.id,
                submitted: m.submitted,
                correct: m.correct,
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

fn into_out(paper: core::papers::AssembledPaper) -> AssembledPaperOut {
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
                // Answers withheld: a paper never carries the key.
                questions: sec
                    .questions
                    .iter()
                    .map(|q| core::catalog::render(q, false))
                    .collect(),
            })
            .collect(),
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
            "INSERT INTO subjects VALUES ('physics','JAMB','Physics',0,40)",
            (),
        )
        .await
        .expect("insert subject");
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
}
