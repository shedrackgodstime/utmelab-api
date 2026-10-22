//! The MCP server: tool handlers and the `ServerHandler` impl.
//!
//! One type serves both mounted endpoints, but never at once: a [`Surface`]
//! picks which tool router answers, so the URL, not a scope check alone,
//! decides what a caller can even see. `/mcp` is the catalog surface (reads
//! plus the consumer actions); `/mcp/admin` is key management.
//!
//! Every tool mounts the same function its HTTP twin does (`api::v1`), so a
//! capability is written once. The admin key tools have no twin on the keyed
//! HTTP surface; they call the same `store::accounts` functions the dashboard
//! does. Scope is checked with the same [`Auth::require`] HTTP uses, read from
//! the request the transport carried into `context.extensions`. Each tool
//! declares the scope it needs at its registration, and that one declaration
//! both hides the tool from `tools/list` for a caller who cannot call it and
//! refuses the call.

use axum::extract::{Path, Query, State};
use rmcp::{
    handler::server::{router::tool::ToolRouter, tool::ToolCallContext, wrapper::Parameters},
    model::{
        CallToolRequestParams, CallToolResponse, CallToolResult, ContentBlock, ErrorCode,
        Implementation, ListResourceTemplatesResult, ListResourcesResult, ListToolsResult,
        MetaObject, PaginatedRequestParams, ReadResourceRequestParams, ReadResourceResponse,
        ReadResourceResult, ResourceContents, ServerCapabilities, ServerConfig, Tool,
    },
    service::RequestContext,
    tool, tool_handler, tool_router, ErrorData, RoleServer, ServerHandler,
};
use schemars::JsonSchema;
use serde::Deserialize;

use crate::{
    api::v1::{papers, reports},
    auth::{api_key::AuthedKey, Auth, SCOPE_MANAGE_KEYS, SCOPE_READ_CATALOG, SCOPE_WRITE_REPORTS},
    core,
    state::DbState,
    store,
};

use super::{resources, to_mcp};

/// Which capability set an endpoint serves. The split is by URL, so an admin
/// tool is unreachable from a consumer key rather than merely refused when it
/// is called.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Surface {
    /// The keyed catalog: `utmelab://catalog` reads and the consumer actions.
    Catalog,
    /// Key administration. Gated at the router with `manage:keys`.
    Admin,
}

/// One MCP server instance. Stateless: it holds the replica handle, the surface
/// it serves, and both tool routers, and reads each caller's identity from the
/// request it is answering, so one instance serves every key.
#[derive(Clone)]
pub struct McpServer {
    db: DbState,
    surface: Surface,
    catalog_tools: ToolRouter<Self>,
    admin_tools: ToolRouter<Self>,
}

impl McpServer {
    pub fn new(db: DbState, surface: Surface) -> Self {
        Self {
            db,
            surface,
            catalog_tools: Self::catalog_router(),
            admin_tools: Self::admin_router(),
        }
    }

    /// The router the served surface exposes. `#[tool_handler]` dispatches
    /// through this, so `tools/list` and `tools/call` can only reach what the
    /// URL offers.
    fn tools(&self) -> &ToolRouter<Self> {
        match self.surface {
            Surface::Catalog => &self.catalog_tools,
            Surface::Admin => &self.admin_tools,
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

/// The `_meta` key that carries a tool's required scope. Namespaced, as `_meta`
/// keys must be.
const SCOPE_KEY: &str = "io.utmelab/requiredScope";

/// The `_meta` a tool carries. Declaring the scope beside the tool is what lets
/// listing and dispatch share one declaration: [`list_tools`] hides a tool the
/// caller's scopes cannot reach and `call_tool` refuses it, both by asking
/// [`scope_of`]. The requirement stays on the wire because the vocabulary is
/// public already (the docs name every scope), so a client can check before it
/// calls instead of learning the rule from a refusal.
///
/// [`list_tools`]: McpServer::list_tools
fn scope_meta(scope: &'static str) -> MetaObject {
    let mut meta = MetaObject::new();
    meta.insert(SCOPE_KEY.to_string(), serde_json::Value::from(scope));
    meta
}

/// The scope a tool declared, or `None` for a tool that requires none.
fn scope_of(tool: &Tool) -> Option<&str> {
    tool.meta.as_ref()?.get(SCOPE_KEY)?.as_str()
}

/// Tool arguments. An optional field carries `extend("type" = ...)` so its
/// schema renders a plain type: schemars spells `Option<T>` as `["T","null"]`,
/// which is legal but less portable, since a client that maps onto a
/// single-`type` dialect (Gemini's OpenAPI subset) may reject the tool or drop
/// the constraint. The field is already outside `required`, so the `null`
/// branch describes nothing a caller needs.
#[derive(Deserialize, JsonSchema)]
struct FileReportArgs {
    /// One of: question, topic, passage, novel.
    target_type: String,
    /// The target's id. A topic has no single id, so its id is the
    /// slash-joined `exam/subject/slug`.
    target_id: String,
    /// One of: wrong_answer, unclear_stem, broken_option, wrong_explanation,
    /// other.
    reason: String,
    /// Optional context. No PII.
    #[schemars(extend("type" = "string"))]
    detail: Option<String>,
}

#[derive(Deserialize, JsonSchema)]
struct AssemblePaperArgs {
    /// Exam code, e.g. `JAMB`.
    exam: String,
    /// Subject slug, e.g. `physics`.
    subject: String,
    /// Deterministic draw: same seed, same paper. Defaults to 1.
    #[schemars(extend("type" = "integer"))]
    seed: Option<u64>,
    /// Country scope, e.g. `NG`.
    #[schemars(extend("type" = "string"))]
    country: Option<String>,
    /// Include answers and explanations. Defaults to false.
    #[schemars(extend("type" = "boolean"))]
    include_explanation: Option<bool>,
    /// Include companion passages for reading items. Defaults to false.
    #[schemars(extend("type" = "boolean"))]
    include_passage: Option<bool>,
}

#[derive(Deserialize, JsonSchema)]
struct ScorePaperArgs {
    /// Exam code, e.g. `JAMB`.
    exam: String,
    /// Subject slug, e.g. `physics`.
    subject: String,
    /// The seed the paper was assembled with.
    seed: u64,
    /// Country scope, e.g. `NG`.
    #[schemars(extend("type" = "string"))]
    country: Option<String>,
    /// Question id to chosen option id. Unanswered ids are left out on purpose:
    /// a guess not made is never marked.
    answers: std::collections::HashMap<String, String>,
    /// Include answers and explanations with the score. Defaults to false.
    #[schemars(extend("type" = "boolean"))]
    include_explanation: Option<bool>,
}

#[derive(Deserialize, JsonSchema)]
struct PrefixArgs {
    /// Key prefix, e.g. `live` from `live.secret`.
    prefix: String,
}

#[derive(Deserialize, JsonSchema)]
struct CreateKeyArgs {
    /// `commercial` for a consumer key, `admin` for a staff key.
    tier: String,
    /// Owner label for a commercial key, e.g. `utmelab-app`. Ignored for an
    /// admin key, which belongs to the staff.
    #[serde(default)]
    owner: String,
}

/// The catalog surface's actions. Each delegates to the `api::v1` handler its
/// HTTP twin mounts, so the scope check and the rendered shape live once.
#[tool_router(router = catalog_router)]
impl McpServer {
    /// Flag a catalog item (question, topic, passage or novel) for review.
    /// Needs the `write:reports` scope.
    #[tool(
        description = "Flag a catalog item for review. Needs write:reports.",
        meta = scope_meta(SCOPE_WRITE_REPORTS)
    )]
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
    #[tool(
        description = "Assemble a subject paper from the bank. Needs read:catalog.",
        meta = scope_meta(SCOPE_READ_CATALOG)
    )]
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
                include_explanation: args.include_explanation,
                include_passage: args.include_passage,
            }),
        )
        .await
        .map_err(to_mcp)?;
        json_result(&paper)
    }

    /// Re-assemble a paper with the same seed and mark only submitted ids.
    /// Needs the `read:catalog` scope.
    #[tool(
        description = "Score a subject paper by re-assembling it. Needs read:catalog.",
        meta = scope_meta(SCOPE_READ_CATALOG)
    )]
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
                include_explanation: args.include_explanation,
            }),
        )
        .await
        .map_err(to_mcp)?;
        json_result(&scored)
    }
}

/// The admin surface's actions. These have no keyed HTTP twin; they call the
/// same store functions the dashboard does, behind the same `manage:keys`
/// scope the router already enforced.
#[tool_router(router = admin_router)]
impl McpServer {
    /// Grant a key. The tier decides the scopes, so this mints a consumer key
    /// or a staff key and nothing in between. Needs the `manage:keys` scope.
    #[tool(
        description = "Create a key. tier is commercial or admin; owner labels a commercial key. Needs manage:keys.",
        meta = scope_meta(SCOPE_MANAGE_KEYS)
    )]
    async fn create_key(
        &self,
        Parameters(args): Parameters<CreateKeyArgs>,
        context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let auth = auth_from(&context)?;
        auth.require(SCOPE_MANAGE_KEYS).map_err(to_mcp)?;
        let key = store::accounts::create_key_spec(
            &self.db,
            &format!("key:{}", auth.key_id),
            &args.tier,
            &args.owner,
        )
        .await
        .map_err(to_mcp)?;
        json_result(&core::models::NewKey { key })
    }

    /// Revoke a key by prefix. Needs the `manage:keys` scope.
    #[tool(
        description = "Revoke a key by prefix. Needs manage:keys.",
        meta = scope_meta(SCOPE_MANAGE_KEYS)
    )]
    async fn revoke_key(
        &self,
        Parameters(args): Parameters<PrefixArgs>,
        context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        self.set_revoked(&args.prefix, true, &context).await
    }

    /// Undo a revocation by prefix. Needs the `manage:keys` scope.
    #[tool(
        description = "Undo a key revocation by prefix. Needs manage:keys.",
        meta = scope_meta(SCOPE_MANAGE_KEYS)
    )]
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
        description = "Rotate a key: mint a replacement, revoke the old prefix. Needs manage:keys.",
        meta = scope_meta(SCOPE_MANAGE_KEYS)
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
    /// presenting key, so the audit line names it. `require` runs again here
    /// even though the router gated the surface: a capability is never guarded
    /// by the mount alone.
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

#[tool_handler(router = self.tools())]
impl ServerHandler for McpServer {
    /// Only the tools this caller can invoke are listed, so the advertised and
    /// the callable sets agree. The scope each tool declares at its
    /// registration is the same one `call_tool` enforces, so listing cannot
    /// drift from dispatch.
    async fn list_tools(
        &self,
        _request: Option<PaginatedRequestParams>,
        context: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, ErrorData> {
        let auth = auth_from(&context)?;
        let tools = self
            .tools()
            .list_all()
            .into_iter()
            .filter(|tool| scope_of(tool).is_none_or(|scope| auth.has_scope(scope)))
            .collect();
        Ok(ListToolsResult::with_all_items(tools))
    }

    /// Enforce the scope the tool declared before dispatching, so a tool that
    /// `list_tools` hides is also refused when called by name. An unknown tool
    /// declares nothing and falls through to the router's own "tool not found".
    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let auth = auth_from(&context)?;
        let required = self
            .tools()
            .get(&request.name)
            .and_then(scope_of)
            .map(str::to_owned);
        if let Some(scope) = required {
            auth.require(&scope).map_err(to_mcp)?;
        }
        self.tools()
            .call(ToolCallContext::new(self, request, context))
            .await
    }

    fn get_info(&self) -> ServerConfig {
        match self.surface {
            Surface::Catalog => ServerConfig::new(
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
            ),
            Surface::Admin => {
                ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
                    .with_server_info(Implementation::new(
                        "utmelab-api-admin",
                        env!("CARGO_PKG_VERSION"),
                    ))
                    .with_instructions(
                        "UTME Lab key administration: revoke, unrevoke and rotate API keys \
                 by prefix. Needs manage:keys.",
                    )
            }
        }
    }

    async fn list_resources(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListResourcesResult, ErrorData> {
        // The admin surface serves tools only and advertises no resources, so
        // it cannot be used to read the catalog.
        let items = match self.surface {
            Surface::Catalog => resources::list(),
            Surface::Admin => Vec::new(),
        };
        Ok(ListResourcesResult::with_all_items(items))
    }

    async fn list_resource_templates(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListResourceTemplatesResult, ErrorData> {
        let items = match self.surface {
            Surface::Catalog => resources::templates(),
            Surface::Admin => Vec::new(),
        };
        Ok(ListResourceTemplatesResult::with_all_items(items))
    }

    async fn read_resource(
        &self,
        request: ReadResourceRequestParams,
        context: RequestContext<RoleServer>,
    ) -> Result<ReadResourceResponse, ErrorData> {
        if self.surface != Surface::Catalog {
            return Err(ErrorData::new(
                ErrorCode::METHOD_NOT_FOUND,
                "the admin surface serves tools only",
                None,
            ));
        }
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
