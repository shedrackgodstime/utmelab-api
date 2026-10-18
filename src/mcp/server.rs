//! The MCP server: tool handlers and the `ServerHandler` impl.
//!
//! Every tool mounts the same function its HTTP twin does (`api::v1`), so a
//! capability is written once. The admin key tools have no twin on the keyed
//! HTTP surface; they call the same `store::accounts` functions the dashboard
//! does. Scope is checked with the same [`Auth::require`] HTTP uses, read from
//! the request the transport carried into `context.extensions`.

use axum::extract::{Path, Query, State};
use rmcp::{
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    model::{
        CallToolResponse, CallToolResult, ContentBlock, ErrorCode, Implementation,
        ListResourceTemplatesResult, ListResourcesResult, PaginatedRequestParams,
        ReadResourceRequestParams, ReadResourceResponse, ReadResourceResult, ResourceContents,
        ServerCapabilities, ServerConfig,
    },
    service::RequestContext,
    tool, tool_handler, tool_router, ErrorData, RoleServer, ServerHandler,
};
use schemars::JsonSchema;
use serde::Deserialize;

use crate::{
    api::v1::{papers, reports},
    auth::{api_key::AuthedKey, Auth, SCOPE_MANAGE_KEYS},
    core,
    state::DbState,
    store,
};

use super::{resources, to_mcp};

/// One MCP server instance. Stateless: it holds only the replica handle and
/// the tool router, and reads each caller's identity from the request it is
/// answering, so one instance serves every key.
#[derive(Clone)]
pub struct McpServer {
    db: DbState,
    tool_router: ToolRouter<Self>,
}

impl McpServer {
    pub fn new(db: DbState) -> Self {
        Self {
            db,
            tool_router: Self::tool_router(),
        }
    }
}

/// The caller's identity, put on the request by `verify_key` and carried into
/// the message by the transport. Absent means the surface was mounted without
/// its gate, which fails closed.
fn auth_from(context: &RequestContext<RoleServer>) -> Result<Auth, ErrorData> {
    context
        .extensions
        .get::<axum::http::request::Parts>()
        .and_then(|parts| parts.extensions.get::<Auth>())
        .cloned()
        .ok_or_else(|| {
            ErrorData::new(
                ErrorCode::INTERNAL_ERROR,
                "no authenticated key on the request",
                None,
            )
        })
}

/// Render a serialisable value as one JSON text content block, which is what a
/// client that reads only text content will see.
fn json_result<T: serde::Serialize>(value: &T) -> Result<CallToolResponse, ErrorData> {
    let text = serde_json::to_string_pretty(value)
        .map_err(|e| ErrorData::internal_error(e.to_string(), None))?;
    Ok(CallToolResult::success(vec![ContentBlock::text(text)]).into())
}

#[derive(Deserialize, JsonSchema)]
struct FileReportArgs {
    /// One of: question, topic, passage, novel.
    pub target_type: String,
    /// The target's id. A topic has no single id, so its is the slash-joined
    /// `exam/subject/slug`.
    pub target_id: String,
    /// One of: wrong_answer, unclear_stem, broken_option, wrong_explanation,
    /// other.
    pub reason: String,
    /// Optional context. No PII.
    pub detail: Option<String>,
}

#[derive(Deserialize, JsonSchema)]
struct AssemblePaperArgs {
    /// Exam code, e.g. `JAMB`.
    pub exam: String,
    /// Subject slug, e.g. `physics`.
    pub subject: String,
    /// Deterministic draw: same seed, same paper. Defaults to 1.
    pub seed: Option<u64>,
    /// Country scope, e.g. `NG`.
    pub country: Option<String>,
}

#[derive(Deserialize, JsonSchema)]
struct ScorePaperArgs {
    /// Exam code, e.g. `JAMB`.
    pub exam: String,
    /// Subject slug, e.g. `physics`.
    pub subject: String,
    /// The seed the paper was assembled with.
    pub seed: u64,
    /// Country scope, e.g. `NG`.
    pub country: Option<String>,
    /// Question id to chosen option id. Unanswered ids are left out on purpose:
    /// a guess not made is never marked.
    pub answers: std::collections::HashMap<String, String>,
}

#[derive(Deserialize, JsonSchema)]
struct PrefixArgs {
    /// Key prefix, e.g. `live` from `live.secret`.
    pub prefix: String,
}

#[tool_router]
impl McpServer {
    /// Flag a catalog item (question, topic, passage or novel) for review.
    /// Needs the `write:reports` scope.
    #[tool(description = "Flag a catalog item for review. Needs write:reports.")]
    async fn file_report(
        &self,
        Parameters(args): Parameters<FileReportArgs>,
        context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let (_, axum::Json(filed)) = reports::file(
            State(self.db.clone()),
            AuthedKey(auth_from(&context)?),
            axum::Json(reports::ReportBody {
                target_type: args.target_type,
                target_id: args.target_id,
                reason: args.reason,
                detail: args.detail,
            }),
        )
        .await
        .map_err(to_mcp)?;
        json_result(&filed)
    }

    /// Assemble one subject's mock from the bank. Deterministic per seed,
    /// answers always withheld. Needs the `read:catalog` scope.
    #[tool(description = "Assemble a subject paper from the bank. Needs read:catalog.")]
    async fn assemble_paper(
        &self,
        Parameters(args): Parameters<AssemblePaperArgs>,
        context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let axum::Json(paper) = papers::assemble_paper(
            State(self.db.clone()),
            AuthedKey(auth_from(&context)?),
            Path((args.exam, args.subject)),
            Query(papers::AssembleQuery {
                seed: args.seed,
                country: args.country,
            }),
        )
        .await
        .map_err(to_mcp)?;
        json_result(&paper)
    }

    /// Re-assemble a paper with the same seed and mark only submitted ids.
    /// Needs the `read:catalog` scope.
    #[tool(description = "Score a subject paper by re-assembling it. Needs read:catalog.")]
    async fn score_paper(
        &self,
        Parameters(args): Parameters<ScorePaperArgs>,
        context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let axum::Json(scored) = papers::score_paper(
            State(self.db.clone()),
            AuthedKey(auth_from(&context)?),
            Path((args.exam, args.subject)),
            axum::Json(papers::ScoreRequest {
                seed: args.seed,
                country: args.country,
                answers: args.answers,
            }),
        )
        .await
        .map_err(to_mcp)?;
        json_result(&scored)
    }

    /// Revoke a key by prefix. Needs the `manage:keys` scope.
    #[tool(description = "Revoke a key by prefix. Needs manage:keys.")]
    async fn revoke_key(
        &self,
        Parameters(args): Parameters<PrefixArgs>,
        context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        self.set_revoked(&args.prefix, true, &context).await
    }

    /// Undo a revocation by prefix. Needs the `manage:keys` scope.
    #[tool(description = "Undo a key revocation by prefix. Needs manage:keys.")]
    async fn unrevoke_key(
        &self,
        Parameters(args): Parameters<PrefixArgs>,
        context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        self.set_revoked(&args.prefix, false, &context).await
    }

    /// Mint a replacement for a key and revoke the old prefix. Needs the
    /// `manage:keys` scope.
    #[tool(
        description = "Rotate a key: mint a replacement, revoke the old prefix. Needs manage:keys."
    )]
    async fn rotate_key(
        &self,
        Parameters(args): Parameters<PrefixArgs>,
        context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let auth = auth_from(&context)?;
        auth.require(SCOPE_MANAGE_KEYS).map_err(to_mcp)?;
        let key =
            store::accounts::rotate_key(&self.db, &args.prefix, &format!("key:{}", auth.key_id))
                .await
                .map_err(to_mcp)?;
        json_result(&core::models::NewKey { key })
    }
}

impl McpServer {
    /// The two revoke tools differ only by the flag. The actor is the
    /// presenting key, so the audit line names it.
    async fn set_revoked(
        &self,
        prefix: &str,
        revoked: bool,
        context: &RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let auth = auth_from(context)?;
        auth.require(SCOPE_MANAGE_KEYS).map_err(to_mcp)?;
        let actor = format!("key:{}", auth.key_id);
        let ok = store::accounts::set_revoked(&self.db, prefix, revoked, &actor)
            .await
            .map_err(to_mcp)?;
        json_result(&core::models::Applied { ok })
    }
}

#[tool_handler(router = self.tool_router)]
impl ServerHandler for McpServer {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(
            ServerCapabilities::builder()
                .enable_tools()
                .enable_resources()
                .build(),
        )
        .with_server_info(Implementation::new(
            "utmelab-api",
            env!("CARGO_PKG_VERSION"),
        ))
        .with_instructions(
            "UTME Lab catalog: JAMB (and other exam) questions, subjects, \
             syllabus, blueprints, novels and papers. Reads are resources under \
             `utmelab://catalog/...`; reports and paper assembly are tools.",
        )
    }

    async fn list_resources(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListResourcesResult, ErrorData> {
        Ok(ListResourcesResult::with_all_items(resources::list()))
    }

    async fn list_resource_templates(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListResourceTemplatesResult, ErrorData> {
        Ok(ListResourceTemplatesResult::with_all_items(
            resources::templates(),
        ))
    }

    async fn read_resource(
        &self,
        request: ReadResourceRequestParams,
        context: RequestContext<RoleServer>,
    ) -> Result<ReadResourceResponse, ErrorData> {
        let auth = auth_from(&context)?;
        let uri = request.uri;
        let value = resources::read(&self.db, &auth, &uri)
            .await
            .map_err(to_mcp)?;
        let text = serde_json::to_string_pretty(&value)
            .map_err(|e| ErrorData::internal_error(e.to_string(), None))?;
        Ok(
            ReadResourceResult::new(vec![ResourceContents::TextResourceContents {
                uri,
                mime_type: Some("application/json".into()),
                text,
                meta: None,
            }])
            .into(),
        )
    }
}
