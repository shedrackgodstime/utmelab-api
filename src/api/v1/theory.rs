use axum::{
    extract::{Path, Query, State},
    routing::{get, post},
    Json, Router,
};

use crate::{
    auth::{api_key::AuthedKey, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

async fn verify_exam_subject(s: &DbState, exam: &str, subject: &str) -> Result<(), AppError> {
    if store::catalog::get_exam(s, exam).await?.is_none() {
        return Err(AppError::NotFound);
    }
    if store::catalog::get_subject(s, exam, subject)
        .await?
        .is_none()
    {
        return Err(AppError::NotFound);
    }
    Ok(())
}

fn prepare_theory_question(
    mut q: core::models::TheoryQuestion,
    media_base_url: &str,
    include_rubric: bool,
) -> Result<core::models::RenderedTheoryQuestion, AppError> {
    core::catalog::resolve_rich_text(&mut q.stem, media_base_url);
    if let Some(ref mut url) = q.diagram_url {
        *url = core::catalog::resolve_media_url(url, media_base_url);
    }

    let rendered = core::models::RenderedTheoryQuestion {
        id: q.id,
        exam: q.exam,
        subject: q.subject,
        year: q.year,
        paper: q.paper,
        section: q.section,
        question_number: q.question_number,
        topic_slug: q.topic_slug,
        subtopic_slug: q.subtopic_slug,
        total_marks: q.total_marks,
        stem: q.stem,
        diagram_url: q.diagram_url,
        sub_parts: q.sub_parts,
        formulation_bridge: q.formulation_bridge,
        marking_methods: if include_rubric {
            Some(q.marking_methods)
        } else {
            None
        },
        diagram_rubric: if include_rubric {
            q.diagram_rubric
        } else {
            None
        },
        penalties: if include_rubric {
            Some(q.penalties)
        } else {
            None
        },
        examiner_report: if include_rubric {
            Some(q.examiner_report)
        } else {
            None
        },
        includes_rubric: include_rubric,
    };

    let size = serde_json::to_vec(&rendered)
        .map_err(|e| {
            AppError::Internal(format!(
                "rendered theory question serialization failed: {e}"
            ))
        })?
        .len();
    if size >= crate::routes::MAX_BODY_BYTES {
        return Err(AppError::Internal(format!(
            "rendered theory question {} serializes to {size} bytes, over the {} byte ceiling",
            rendered.id,
            crate::routes::MAX_BODY_BYTES
        )));
    }

    Ok(rendered)
}

#[derive(Debug, serde::Deserialize)]
pub struct TheoryListParams {
    pub year: Option<u32>,
    pub topic: Option<String>,
    pub section: Option<String>,
    pub page: Option<u32>,
    pub per_page: Option<u32>,
}

#[utoipa::path(
    get,
    path = "/api/v1/theory/{exam}/{subject}",
    tag = "catalog",
    operation_id = "listTheoryQuestions",
    summary = "Paged list of Paper 2 theory questions with filtering.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `WAEC` or `NECO`."),
        ("subject" = String, Path, description = "Subject slug, e.g. `general-mathematics` or `physics`."),
        ("year" = Option<u32>, Query, description = "Optional examination year filter, e.g. 2023."),
        ("topic" = Option<String>, Query, description = "Optional syllabus topic slug filter."),
        ("section" = Option<String>, Query, description = "Optional paper section filter, e.g. `Section A`."),
        ("page" = Option<u32>, Query, description = "Page number (defaults to 1)."),
        ("per_page" = Option<u32>, Query, description = "Items per page (1 to 200, defaults to 20)."),
    ),
    responses(
        (status = 200, body = core::models::Page<core::models::TheoryQuestionSummary>),
        (status = 404, description = "Exam or subject not found", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn list_theory(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject)): Path<(String, String)>,
    Query(params): Query<TheoryListParams>,
) -> Result<Json<core::models::Page<core::models::TheoryQuestionSummary>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    verify_exam_subject(&s, &exam, &subject).await?;
    let page = store::catalog::list_theory_questions(
        &s,
        &exam,
        &subject,
        params.year,
        params.topic.as_deref(),
        params.section.as_deref(),
        params.page.unwrap_or(1),
        params.per_page.unwrap_or(20),
    )
    .await?;
    Ok(Json(page))
}

#[derive(Debug, serde::Deserialize)]
pub struct TheoryGetParams {
    pub include_rubric: Option<bool>,
}

#[utoipa::path(
    get,
    path = "/api/v1/theory/{exam}/{subject}/{id}",
    tag = "catalog",
    operation_id = "getTheoryQuestion",
    summary = "Paper 2 theory question with practice or full rubric view.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `WAEC`."),
        ("subject" = String, Path, description = "Subject slug, e.g. `physics`."),
        ("id" = String, Path, description = "Theory question identifier."),
        ("include_rubric" = Option<bool>, Query, description = "Whether to include full marking rubric (defaults to false)."),
    ),
    responses(
        (status = 200, body = core::models::RenderedTheoryQuestion),
        (status = 404, description = "Question not found", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn get_theory(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject, id)): Path<(String, String, String)>,
    Query(params): Query<TheoryGetParams>,
) -> Result<Json<core::models::RenderedTheoryQuestion>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    verify_exam_subject(&s, &exam, &subject).await?;
    let question = store::catalog::get_theory_question(&s, &exam, &subject, &id).await?;
    let include_rubric = params.include_rubric.unwrap_or(false);
    match question {
        Some(q) => Ok(Json(prepare_theory_question(
            q,
            s.media_base_url.as_ref(),
            include_rubric,
        )?)),
        None => Err(AppError::NotFound),
    }
}

#[utoipa::path(
    get,
    path = "/api/v1/theory/{exam}/{subject}/{id}/rubric",
    tag = "catalog",
    operation_id = "getTheoryRubric",
    summary = "Complete step-by-step marking rubric with M/A/B marks and Chief Examiner notes.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `WAEC`."),
        ("subject" = String, Path, description = "Subject slug, e.g. `physics`."),
        ("id" = String, Path, description = "Theory question identifier."),
    ),
    responses(
        (status = 200, body = core::models::RenderedTheoryQuestion),
        (status = 404, description = "Question not found", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn get_theory_rubric(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject, id)): Path<(String, String, String)>,
) -> Result<Json<core::models::RenderedTheoryQuestion>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    verify_exam_subject(&s, &exam, &subject).await?;
    let question = store::catalog::get_theory_question(&s, &exam, &subject, &id).await?;
    match question {
        Some(q) => Ok(Json(prepare_theory_question(
            q,
            s.media_base_url.as_ref(),
            true,
        )?)),
        None => Err(AppError::NotFound),
    }
}

#[utoipa::path(
    post,
    path = "/api/v1/theory/{exam}/{subject}/{id}/evaluate",
    tag = "catalog",
    operation_id = "evaluateTheorySubmission",
    summary = "Evaluate candidate checklist selections against official WAEC/NECO marking criteria.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `WAEC`."),
        ("subject" = String, Path, description = "Subject slug, e.g. `general-mathematics`."),
        ("id" = String, Path, description = "Theory question identifier."),
    ),
    request_body = core::models::TheoryEvaluationRequest,
    responses(
        (status = 200, body = core::models::TheoryEvaluationResponse),
        (status = 400, description = "Invalid method or submission data", body = crate::core::models::ErrorResponse),
        (status = 404, description = "Question not found", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn evaluate_theory(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject, id)): Path<(String, String, String)>,
    Json(req): Json<core::models::TheoryEvaluationRequest>,
) -> Result<Json<core::models::TheoryEvaluationResponse>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    verify_exam_subject(&s, &exam, &subject).await?;
    let question = store::catalog::get_theory_question(&s, &exam, &subject, &id).await?;
    let Some(q) = question else {
        return Err(AppError::NotFound);
    };
    let response = store::catalog::evaluate_theory_submission(&q, &req)?;
    Ok(Json(response))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/theory/{exam}/{subject}", get(list_theory))
        .route("/v1/theory/{exam}/{subject}/{id}", get(get_theory))
        .route(
            "/v1/theory/{exam}/{subject}/{id}/rubric",
            get(get_theory_rubric),
        )
        .route(
            "/v1/theory/{exam}/{subject}/{id}/evaluate",
            post(evaluate_theory),
        )
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::testing::{
        api_schema, bank_schema, call, connect, issue_key, replica, seed_bank_exam,
        seed_bank_topic, seed_theory_question, state,
    };
    use axum::http::StatusCode;

    async fn seeded_app() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["exams", "subjects", "topics"]).await;
        seed_bank_exam(&conn, "WAEC", "general-mathematics", None).await;
        seed_bank_topic(&conn, "WAEC", "general-mathematics", "algebra").await;
        seed_theory_question(&conn, "wq_waec_2023_math_p2_q4").await;
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        issue_key(&conn, "wrong.secret", "commercial", "write:reports", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    #[tokio::test]
    async fn theory_endpoints_are_keyed_and_scoped() {
        let app = seeded_app().await;

        let (status, _) = call(
            app.clone(),
            "GET",
            "/api/v1/theory/WAEC/general-mathematics",
            None,
            None,
        )
        .await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);

        let (status, _) = call(
            app.clone(),
            "GET",
            "/api/v1/theory/WAEC/general-mathematics",
            Some("wrong.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN);

        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/theory/WAEC/general-mathematics",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["questions"].as_array().expect("array").len(), 1);
        assert_eq!(body["total_records"], 1);
    }

    #[tokio::test]
    async fn practice_view_withholds_rubric_by_default() {
        let app = seeded_app().await;

        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/theory/WAEC/general-mathematics/wq_waec_2023_math_p2_q4",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["id"], "wq_waec_2023_math_p2_q4");
        assert_eq!(body["includes_rubric"], false);
        assert!(body["marking_methods"].is_null());
        assert!(body["examiner_report"].is_null());
        assert_eq!(body["sub_parts"].as_array().expect("parts").len(), 2);
    }

    #[tokio::test]
    async fn rubric_endpoint_reveals_marking_methods_and_examiner_report() {
        let app = seeded_app().await;

        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/theory/WAEC/general-mathematics/wq_waec_2023_math_p2_q4/rubric",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["includes_rubric"], true);
        assert!(body["marking_methods"].is_array());
        assert!(body["examiner_report"].is_object());
        assert_eq!(
            body["diagram_url"],
            "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/images/diagrams/garden.png"
        );
    }

    #[tokio::test]
    async fn evaluate_endpoint_scores_full_marks_when_all_steps_met() {
        let app = seeded_app().await;

        let payload = serde_json::json!({
            "selected_method_id": "m1",
            "achieved_step_ids": ["s1", "s2", "s3", "s4", "s5", "s6"],
            "unit_included": true,
            "intermediate_rounding_avoided": true
        });

        let (status, body) = call(
            app.clone(),
            "POST",
            "/api/v1/theory/WAEC/general-mathematics/wq_waec_2023_math_p2_q4/evaluate",
            Some("reader.secret"),
            Some(&payload.to_string()),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["awarded_marks"], 8);
        assert_eq!(body["total_marks_possible"], 8);
        assert_eq!(body["percentage"], 100.0);
        assert_eq!(
            body["penalties_applied"]
                .as_array()
                .expect("penalties")
                .len(),
            0
        );
    }

    #[tokio::test]
    async fn evaluate_endpoint_forfeits_accuracy_when_method_fails_and_deducts_unit() {
        let app = seeded_app().await;

        // Candidate missed step s2 (method mark M1 in part a).
        // Prerequisite rule: s3 (accuracy mark A1 in part a) must be forfeited (M0 -> A0).
        // Candidate also omitted unit (-1 penalty).
        let payload = serde_json::json!({
            "selected_method_id": "m1",
            "achieved_step_ids": ["s1", "s3", "s4", "s5", "s6"],
            "unit_included": false,
            "intermediate_rounding_avoided": true
        });

        let (status, body) = call(
            app.clone(),
            "POST",
            "/api/v1/theory/WAEC/general-mathematics/wq_waec_2023_math_p2_q4/evaluate",
            Some("reader.secret"),
            Some(&payload.to_string()),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["awarded_marks"], 5);
        assert_eq!(body["total_marks_possible"], 8);
        assert_eq!(body["percentage"], 62.5);
        assert_eq!(
            body["penalties_applied"]
                .as_array()
                .expect("penalties")
                .len(),
            1
        );
        assert_eq!(
            body["penalties_applied"][0]["penalty_type"],
            "unit_omission"
        );
    }

    #[tokio::test]
    async fn theory_queries_requested_exam_not_syllabus_owner() {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["exams", "subjects", "topics"]).await;
        seed_bank_exam(&conn, "WAEC", "general-mathematics", None).await;
        seed_bank_topic(&conn, "WAEC", "general-mathematics", "algebra").await;
        seed_theory_question(&conn, "wq_waec_2023_math_p2_q4").await;
        // NECO delegates its syllabus to WAEC:
        seed_bank_exam(
            &conn,
            "NECO",
            "general-mathematics",
            Some(("WAEC", "general-mathematics")),
        )
        .await;
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        let app = crate::routes::router(state(db), &crate::config::Config::default());

        // NECO request must query NECO's own theory questions (0 found), NOT WAEC's.
        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/theory/NECO/general-mathematics",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["questions"].as_array().expect("array").len(), 0);
        assert_eq!(body["total_records"], 0);

        // Individual question lookup for NECO must also not find the WAEC question.
        let (status, _) = call(
            app,
            "GET",
            "/api/v1/theory/NECO/general-mathematics/wq_waec_2023_math_p2_q4",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::NOT_FOUND);
    }
}
