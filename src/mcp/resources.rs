//! MCP resources: the catalog reads, URI-addressed and read-only, at
//! `/mcp/resources/<tail>` where `<tail>` is the `/api/v1` path without the
//! version. Each route mounts the *same* handler the HTTP route does, so a
//! resource and its HTTP twin cannot drift: there is one implementation, and
//! the parity test only proves the wiring points both at it.
//!
//! A read is a resource (GET, addressable); an action is a tool (see
//! `tools.rs`). That split is the MCP one, and it falls out of the HTTP verb
//! the mirror already has, so neither surface is invented twice.

use axum::{routing::get, Router};

use crate::{
    api::v1::{
        blueprints, exams, keys, meta, novels, papers, passages, questions, subjects, topics,
    },
    state::AppState,
};

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/mcp/resources/exams", get(exams::list))
        .route(
            "/mcp/resources/exams/{exam}/subjects",
            get(subjects::by_exam),
        )
        .route("/mcp/resources/exams/{exam}/papers", get(papers::readiness))
        .route(
            "/mcp/resources/subjects/{exam}/{slug}",
            get(subjects::subject),
        )
        .route(
            "/mcp/resources/subjects/{exam}/{slug}/syllabus",
            get(subjects::syllabus),
        )
        .route(
            "/mcp/resources/subjects/{exam}/{slug}/coverage",
            get(subjects::coverage),
        )
        .route(
            "/mcp/resources/topics/{exam}/{subject}/{slug}",
            get(topics::one),
        )
        .route(
            "/mcp/resources/blueprints/{exam}/{subject}",
            get(blueprints::list),
        )
        .route("/mcp/resources/passages/{id}", get(passages::one))
        .route("/mcp/resources/novels", get(novels::list))
        .route("/mcp/resources/novels/{id}", get(novels::detail))
        .route(
            "/mcp/resources/novels/{id}/questions",
            get(novels::questions),
        )
        .route("/mcp/resources/questions", get(questions::list))
        .route("/mcp/resources/questions/{id}", get(questions::one))
        .route("/mcp/resources/meta/tables", get(meta::tables))
        .route("/mcp/resources/meta/rows/{table}", get(meta::rows))
        .route("/mcp/resources/keys/me", get(keys::me))
}
