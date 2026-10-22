//! The machine-readable contract: the public `/api/v1` surface as OpenAPI 3.1.
//!
//! Derived, not hand-maintained. Schemas come from `#[derive(ToSchema)]` on the
//! types the handlers return, and paths come from `#[utoipa::path]` on the
//! handlers themselves, so a field cannot exist in the JSON and be missing here,
//! and a route cannot be served without being described.
//!
//! Only the public, keyed `/api/v1` surface is documented. The session-only
//! `/api/internal/*` dashboard and the `/mcp` JSON-RPC surface are ours, not a
//! consumer's, so they stay out for the same reason the MCP admin tools do.
//!
//! The API binary serves no document route. `site/openapi.json` is generated
//! from [`document`] and checked in, because the docs build reads a file for
//! determinism and the static site ships it at `/openapi.json`; the test below
//! regenerates it under `UPDATE_SPEC=1` and otherwise fails the moment it
//! drifts from the code.

use utoipa::openapi::security::{ApiKey, ApiKeyValue, SecurityScheme};
use utoipa::{Modify, OpenApi};

use crate::api::v1::{
    blueprints, exams, keys, meta, novels, papers, passages, public, questions, reports, subjects,
    topics,
};

/// The whole contract, as a value. `site/openapi.json` is this serialised.
pub fn document() -> utoipa::openapi::OpenApi {
    ApiDoc::openapi()
}

const AUTH_NOTE: &str = "Send your key in the `X-API-Key` header. One key type: it works from \
a server, an app, or curl — we never ask where it lives. If you embed it in a client app it can \
be extracted, and whoever extracts it shares your quota.";

/// Adds the one security scheme, including the explanation utoipa has no field
/// for.
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
        title = "UTME Lab API",
        version = "0.1.0",
        description = "A keyed question bank for Nigerian entry exams. Every question is keyed \
to a subtopic so a weak spot is a twenty-question sitting rather than a mock. Explanations \
carry the trap that catches people. Send your key in the `X-API-Key` header; the whole \
surface is keyed.",
    ),
    servers((url = "https://api.utmelab.com", description = "Production")),
    paths(
        exams::list,
        subjects::by_exam,
        subjects::subject,
        subjects::syllabus,
        subjects::coverage,
        topics::one,
        blueprints::list,
        passages::list,
        passages::one,
        novels::list,
        novels::detail,
        novels::questions,
        questions::list,
        questions::sample,
        questions::one,
        keys::me,
        meta::tables,
        meta::rows,
        papers::readiness,
        papers::assemble_paper,
        papers::score_paper,
        reports::file,
        public::summary,
        public::exams,
        public::syllabus,
    ),
    components(schemas(
        crate::core::models::Exam,
        crate::core::models::Subject,
        crate::core::models::Topic,
        crate::core::models::Blueprint,
        crate::core::models::Passage,
        crate::core::models::Novel,
        crate::core::models::NovelDoc,
        crate::core::models::NovelChapter,
        crate::core::models::NovelCharacter,
        crate::core::models::NovelTheme,
        crate::core::models::NovelQuestion,
        crate::core::models::RichText,
        crate::core::models::Inline,
        crate::core::models::InlineKind,
        crate::core::models::ImagePosition,
        crate::core::models::Choice,
        crate::core::models::Explanation,
        crate::core::models::Requirement,
        crate::core::models::SubjectSlot,
        crate::core::models::Scheme,
        crate::core::models::PaperReadiness,
        crate::core::models::Page<crate::core::models::RenderedQuestion>,
        crate::core::models::Page<crate::core::models::RenderedNovelQuestion>,
        crate::core::models::RenderedQuestion,
        crate::core::models::SampledQuestions,
        crate::core::models::RenderedNovelQuestion,
        crate::core::models::ReportFiled,
        crate::core::models::Syllabus,
        crate::core::models::SyllabusTopic,
        crate::core::models::SyllabusSubtopic,
        crate::core::models::SyllabusSummary,
        crate::core::models::Coverage,
        crate::core::models::TableRef,
        crate::core::models::RowPage,
        crate::core::models::KeyInfo,
        crate::core::papers::PaperMode,
        papers::PaperSectionOut,
        papers::AssembledPaperOut,
        papers::ScoredQuestion,
        papers::ScoredPaper,
        papers::ScoreRequest,
        reports::ReportBody,
    )),
    security(("ApiKeyAuth" = [])),
    modifiers(&AuthScheme),
    tags(
        (name = "public", description = "What is in the bank, before you have a key. No credential, coarse on purpose."),
        (name = "catalog", description = "Exams, subjects, syllabi, topics, blueprints, passages and prescribed texts."),
        (name = "questions", description = "The metered question surface."),
        (name = "papers", description = "Seeded assembly and server-side scoring."),
        (name = "account", description = "The calling key."),
        (name = "meta", description = "The tables the bank exposes."),
        (name = "reports", description = "Consumer flags against bank records."),
    )
)]
struct ApiDoc;

#[cfg(test)]
mod tests {
    use super::*;

    /// The spec is generated, never hand-written: this rewrites
    /// `site/openapi.json` under `UPDATE_SPEC=1` and otherwise fails the moment
    /// it drifts from the code. `site/apps/docs` reads that file at build time,
    /// so a stale spec would ship lying reference pages.
    #[test]
    fn the_checked_in_spec_matches_the_code() {
        let rendered = format!(
            "{}\n",
            serde_json::to_string_pretty(&document()).expect("the document serialises")
        );
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("site/openapi.json");
        if std::env::var_os("UPDATE_SPEC").is_some() {
            std::fs::write(&path, &rendered).expect("write the spec");
            return;
        }
        let checked_in = std::fs::read_to_string(&path).expect("site/openapi.json is checked in");
        assert_eq!(
            checked_in, rendered,
            "site/openapi.json is stale; run `UPDATE_SPEC=1 cargo test openapi` to regenerate"
        );
    }
}
