//! `GET /openapi.json` — the machine-readable contract (D25).
//!
//! **Derived, not hand-maintained.** Schemas come from `#[derive(ToSchema)]` on the
//! types the handlers actually return, so a field cannot exist in the JSON and be
//! missing here — the bug class the old hand-written spec kept producing
//! (`securitySchemes` emitted as `security_schemes`; an `integer` parameter
//! carrying a string default).
//!
//! What stays hand-written is only what utoipa cannot infer: prose, the servers
//! list, and the security scheme's explanation.
//!
//! **The router stays ours.** `utoipa-axum`'s `OpenApiRouter` would fuse the spec to
//! the router, which conflicts with D29 — `api/` and `app/` are separate surfaces and
//! the dashboard must exist with no spec at all. So the path list is explicit here,
//! and `tests/openapi.rs` calls every one to keep it honest.

use axum::Json;
use axum::Router;
use axum::routing::get;
use utoipa::openapi::security::{ApiKey, ApiKeyValue, SecurityScheme};
use utoipa::{Modify, OpenApi};

use crate::AppState;
use crate::api::v1::{
    blueprints, exams, keys, novels, papers, passages, questions, reports, subjects, topics,
};

pub fn router() -> Router<AppState> {
    Router::new().route("/openapi.json", get(spec))
}

pub async fn spec() -> Json<utoipa::openapi::OpenApi> {
    Json(document())
}

/// The document, also used by tests that assert against it without HTTP.
pub fn document() -> utoipa::openapi::OpenApi {
    ApiDoc::openapi()
}

/// `/health` and `/openapi.json` are real handlers elsewhere; these carry only the
/// documentation, so the contract can name them without a route item here.
#[utoipa::path(
    get,
    path = "/health",
    tag = "meta",
    operation_id = "health",
    description = "Unauthenticated. Reports question and withheld-record counts.",
    responses((status = 200, description = "Service is up")),
)]
pub fn health_operation() {}

#[utoipa::path(
    get,
    path = "/openapi.json",
    tag = "meta",
    operation_id = "openapi",
    description = "This document.",
    responses((status = 200, description = "The OpenAPI description")),
)]
pub fn openapi_operation() {}

const AUTH_NOTE: &str = "Send your key in the `X-API-Key` header. One key type: it works from \
a server, an app, or curl — we never ask where it lives. If you embed it in a client app it can \
be extracted, and whoever extracts it shares your quota.";

/// Adds the one security scheme, including the explanation utoipa has no field for.
struct AuthScheme;

impl Modify for AuthScheme {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "ApiKeyAuth",
                SecurityScheme::ApiKey(ApiKey::Header(ApiKeyValue::with_description(
                    "X-API-Key",
                    AUTH_NOTE,
                ))),
            );
        }
    }
}

#[derive(OpenApi)]
#[openapi(
    info(
        title = "UTME Lab Question Bank API",
        version = "0.1.0",
        description = "Every candidate writes English plus three others. Questions are keyed \
to subtopics so a weak spot is a 20-question sitting, not a 40-question paper. Explanations \
are Markdown and carry the trap that catches people.",
    ),
    servers((url = "https://api.utmelab.com", description = "Production")),
    paths(
        health_operation,
        openapi_operation,
        exams::list,
        exams::subjects,
        subjects::subject,
        subjects::syllabus,
        keys::me,
        questions::questions,
        questions::question_by_id,
        novels::list,
        novels::detail,
        novels::questions,
        reports::report,
        papers::readiness,
        papers::assemble_paper,
        papers::score_paper,
        passages::passage,
        topics::topic,
        subjects::coverage,
        blueprints::blueprints,
    ),
    components(schemas(
        exams::ExamList,
        exams::Exam,
        exams::ExamSubjects,
        exams::SubjectEnvelope,
        questions::QuestionPage,
        novels::NovelList,
        novels::NovelQuestionPage,
        passages::PassageEnvelope,
        topics::TopicDetail,
        topics::TopicSubtopic,
        blueprints::BlueprintResponse,
        blueprints::BlueprintTopic,
        subjects::Coverage,
        reports::ReportBody,
        reports::ReportReceipt,
        papers::PaperReadiness,
        papers::AssembledPaperOut,
        crate::bank::PaperMode,
        papers::PaperSectionOut,
        papers::ReadinessGapOut,
        papers::ScoreRequest,
        papers::ScoredQuestion,
        papers::ScoreResponse,
        crate::bank::scheme::SubjectSlot,
    )),
    modifiers(&AuthScheme),
    tags(
        (name = "catalog", description = "Exams, subjects and syllabi. No key required."),
        (name = "questions", description = "The metered surface. Requires a key."),
        (name = "account", description = "The calling key."),
        (name = "novels", description = "Prescribed texts: book, chapters, characters, themes, quiz."),
        (name = "meta", description = "Service health and this document."),
    )
)]
struct ApiDoc;
