//! `GET /api/v1/blueprints/{exam}/{subject}` — measured expectations ×
//! coverage, opt-in only (D63).
//!
//! Blueprints never ride the default syllabus response: JAMB publishes no
//! per-topic counts, and the rows are empirical (TestDriller 17yr for
//! maths, Examkits section shares elsewhere). A consumer that wants
//! priority-ordered revision asks here explicitly and gets the readiness
//! account with provenance on every row.

use axum::Json;
use axum::Router;
use axum::extract::{Path, Query, State};
use axum::routing::get;
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

use crate::AppState;
use crate::bank::{SubjectReadiness, TopicReadiness};
use crate::error::ApiError;

#[derive(Serialize, ToSchema)]
pub struct BlueprintTopic {
    pub topic: String,
    pub name: String,
    pub expected: f64,
    pub need: u32,
    pub held: usize,
    pub verified: usize,
    pub deduped: usize,
    pub ready: bool,
    pub method: String,
    pub source: Option<String>,
    pub confidence: Option<String>,
}

#[derive(Serialize, ToSchema)]
pub struct BlueprintResponse {
    pub exam: String,
    pub subject: String,
    pub topics: Vec<BlueprintTopic>,
    pub ready: usize,
    pub total: usize,
    /// Every measured topic is ready. Only a **verdict** when `governed` —
    /// otherwise this is coverage arithmetic, not a promise (D71).
    pub complete: bool,
    /// Does the blueprint predicate govern this subject's papers? False means
    /// papers are served by the count gate, and `complete` must not be read as
    /// "we can build you a balanced mock" (D71).
    pub governed: bool,
    /// Exam cohorts the subject holds. The D71 input, shown so a consumer can
    /// see why a single-cohort bank reports coverage rather than readiness.
    pub cohorts: Vec<u16>,
    pub unattributed: usize,
}

#[derive(Deserialize)]
pub struct BlueprintQuery {
    pub country: Option<String>,
}

pub fn router() -> Router<AppState> {
    Router::new().route("/v1/blueprints/{exam}/{subject}", get(blueprints))
}

#[utoipa::path(
    get,
    path = "/api/v1/blueprints/{exam}/{subject}",
    tag = "catalog",
    operation_id = "getBlueprint",
    summary = "Per-topic expectations against verified coverage.",
    description = "Measured per-topic expectations against verified coverage (D63, provisional, opt-in). A topic is ready when deduped verified rows meet the measured expectation, rounded up. `governed` is false when the measurement does not cover the paper (D70) or the bank holds fewer than two cohorts (D71); then `complete` is coverage, not a promise, and papers come from the count gate.",
    params(
        ("exam" = String, Path, description = "Exam code."),
        ("subject" = String, Path, description = "Subject slug within that exam."),
        ("country" = Option<String>, Query, description = "Country code filter, e.g. GH. Absent means the full honest view."),
    ),
    responses(
        (status = 200, body = BlueprintResponse),
        (status = 404, description = "No such subject, or no blueprint rows"),
    ),
)]
pub async fn blueprints(
    State(state): State<AppState>,
    Path((exam, subject)): Path<(String, String)>,
    Query(f): Query<BlueprintQuery>,
) -> Result<Json<BlueprintResponse>, ApiError> {
    let bank = state.bank.borrow().clone();
    if bank.subject(&exam, &subject).is_none() {
        return Err(ApiError::not_found(
            "subject_not_found",
            format!("No subject with slug '{subject}' for exam '{exam}'."),
        ));
    }
    let rows = bank.blueprints(&exam, &subject);
    if rows.is_empty() {
        return Err(ApiError::not_found(
            "blueprint_not_found",
            format!("No blueprint rows for {exam}/{subject}."),
        ));
    }
    let readiness: SubjectReadiness =
        crate::bank::per_topic(bank.as_ref(), &rows, &exam, &subject, f.country.as_deref());
    if readiness.topics.is_empty() {
        // Rows exist but none measures a topic (unmapped subjects): an
        // all-zero account would invent coverage, so 404 honestly.
        return Err(ApiError::not_found(
            "blueprint_not_found",
            format!("No measured expectations for {exam}/{subject}."),
        ));
    }
    let method_of: std::collections::HashMap<&str, &crate::bank::Blueprint> = rows
        .iter()
        .filter_map(|b| b.topic.as_deref().map(|t| (t, b)))
        .collect();
    Ok(Json(BlueprintResponse {
        exam: readiness.exam.clone(),
        subject: readiness.subject.clone(),
        topics: readiness
            .topics
            .iter()
            .map(|t: &TopicReadiness| {
                let prov = method_of.get(t.topic.as_str());
                BlueprintTopic {
                    topic: t.topic.clone(),
                    name: t.name.clone(),
                    expected: t.expected,
                    need: t.need,
                    held: t.held,
                    verified: t.verified,
                    deduped: t.deduped,
                    ready: t.ready,
                    method: prov.map(|b| b.method.clone()).unwrap_or_default(),
                    source: prov.and_then(|b| b.source.clone()),
                    confidence: prov.and_then(|b| b.confidence.clone()),
                }
            })
            .collect(),
        ready: readiness.ready,
        total: readiness.total(),
        complete: readiness.complete,
        governed: readiness.governed,
        cohorts: readiness.cohorts.clone(),
        unattributed: readiness.unattributed,
    }))
}
