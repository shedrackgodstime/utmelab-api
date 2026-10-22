//! MCP surface: real JSON-RPC 2.0 servers over Streamable HTTP.
//!
//! `rmcp` owns the wire: JSON-RPC framing, capability negotiation, protocol
//! version negotiation, and the resource and tool vocabulary. This module owns
//! only the two things rmcp cannot know: this repo's identity and its
//! catalog. Tools live in [`server`]; resource URIs live in [`resources`].
//!
//! There are two endpoints, split by URL so an admin capability is unreachable
//! from a consumer key rather than merely refused when called:
//!
//! - `/mcp`: the catalog (`utmelab://catalog/...` reads and the consumer
//!   actions: report, assemble, score).
//! - `/mcp/admin`: key administration. Gated twice: the key must verify, and
//!   it must carry `manage:keys` before rmcp sees a message.
//!
//! Identity is the key the HTTP surface already uses. `verify_key` (the same
//! layer `api/v1` mounts) stashes the [`Auth`] in the request extensions before
//! rmcp sees the message; the transport copies the request `Parts` into every
//! JSON-RPC message, so a handler reads its caller from `context.extensions`
//! and checks the same scopes HTTP checks. One identity, one scope vocabulary,
//! one gate.
//!
//! Both servers are stateless: `legacy_session_mode(false)` keeps every request
//! on the stateless path, so no `Mcp-Session-Id` is minted and no protocol
//! state outlives a request. That is what lets one shared instance per surface
//! serve every caller without ever holding someone else's identity.
//!
//! [`Auth`]: crate::auth::Auth

pub mod resources;
pub mod server;

pub use server::{McpServer, Surface};

use std::sync::Arc;

use axum::{
    extract::{FromRef, Request},
    middleware::{from_fn, from_fn_with_state, Next},
    response::{IntoResponse, Response},
    Router,
};
use rmcp::{
    model::ErrorCode,
    transport::streamable_http_server::{
        session::local::LocalSessionManager, StreamableHttpServerConfig, StreamableHttpService,
    },
    ErrorData,
};

use crate::{
    auth::{api_key::verify_key, Auth, SCOPE_MANAGE_KEYS},
    config::Config,
    error::AppError,
    state::{AppState, DbState},
};

pub fn router(state: AppState, cfg: &Config) -> Router<AppState> {
    let db = DbState::from_ref(&state);

    let catalog = Router::new()
        .route_service("/mcp", service(db.clone(), Surface::Catalog))
        .route_layer(from_fn_with_state(state.clone(), verify_key))
        .layer(cfg.slow_timeout());

    let admin = Router::new()
        .route_service("/mcp/admin", service(db, Surface::Admin))
        // `route_layer` wraps last-added outermost, so `verify_key` runs first
        // and the scope check reads the identity it stashed. Without this, the
        // admin tools would still be scope-refused, but only per call; with it,
        // the surface itself is closed.
        .route_layer(from_fn(require_manage_keys))
        .route_layer(from_fn_with_state(state.clone(), verify_key))
        .layer(cfg.slow_timeout());

    catalog.merge(admin).with_state(state)
}

/// One endpoint's rmcp service. Both surfaces share the configuration: stateless
/// (no session outlives a request), JSON-preferred (nothing here emits a
/// notification mid-call), and with the DNS-rebinding host check off, because
/// this server is keyed on every surface and answers one public name behind a
/// proxy: the key is the boundary, and a localhost allowlist would reject real
/// traffic while protecting nothing.
fn service(db: DbState, surface: Surface) -> StreamableHttpService<McpServer, LocalSessionManager> {
    StreamableHttpService::new(
        move || Ok(McpServer::new(db.clone(), surface)),
        Arc::new(LocalSessionManager::default()),
        StreamableHttpServerConfig::default()
            .with_legacy_session_mode(false)
            .with_json_response(true)
            .with_sse_keep_alive(None)
            .disable_allowed_hosts(),
    )
}

/// The admin surface's second gate: it runs after `verify_key`, so the caller's
/// [`Auth`] is already on the request, and refuses anyone without `manage:keys`
/// before rmcp ever sees a JSON-RPC message.
async fn require_manage_keys(request: Request, next: Next) -> Response {
    let allowed = request
        .extensions()
        .get::<Auth>()
        .is_some_and(|auth| auth.has_scope(SCOPE_MANAGE_KEYS));
    if allowed {
        next.run(request).await
    } else {
        AppError::Forbidden.into_response()
    }
}

/// Translate a surface error into a JSON-RPC error. The machine handle and the
/// public sentence are the ones HTTP would send ([`AppError::code`] and
/// [`AppError::public_detail`]), so a client reading either surface sees the
/// same words; the engine text behind a 5xx is logged, never put on the wire.
pub(crate) fn to_mcp(err: AppError) -> ErrorData {
    let code = match &err {
        AppError::BadRequest(_) | AppError::Conflict(_) => ErrorCode::INVALID_PARAMS,
        AppError::NotFound => ErrorCode::RESOURCE_NOT_FOUND,
        AppError::Unauthorized | AppError::Forbidden => ErrorCode::INVALID_REQUEST,
        _ => ErrorCode::INTERNAL_ERROR,
    };
    if let AppError::Internal(msg) | AppError::Upstream(msg) = &err {
        tracing::error!(code = err.code(), error = %msg, "mcp request failed");
    }
    ErrorData::new(
        code,
        err.public_detail(),
        Some(serde_json::json!({ "code": err.code() })),
    )
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use axum::{
        body::Body,
        http::{HeaderName, HeaderValue, Request, StatusCode},
        Router,
    };
    use rmcp::{
        model::{CallToolRequestParams, ReadResourceRequestParams, ResourceContents},
        transport::{
            streamable_http_client::StreamableHttpClientTransportConfig,
            StreamableHttpClientTransport,
        },
        ServiceExt as _,
    };
    use serde_json::{json, Value};
    use tower::ServiceExt;

    use crate::testing::{api_schema, bank_schema, call, connect, issue_key, replica, state};

    const CATALOG: &str = "/mcp";
    const ADMIN: &str = "/mcp/admin";

    /// A replica the surface can answer from: one exam, and keys that cover the
    /// scopes a tool can declare (read, report write, none) plus an admin key.
    async fn app() -> Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["exams"]).await;
        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','Joint Admissions','[\"NG\"]','live',1,4,120,'[\"no calculator\"]')",
            (),
        )
        .await
        .expect("insert exam");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        issue_key(&conn, "writer.secret", "commercial", "write:reports", false).await;
        issue_key(&conn, "nobody.secret", "commercial", "", false).await;
        issue_key(&conn, "admin.secret", "admin", "manage:keys", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// One JSON-RPC message POSTed to `path` with the headers a Streamable HTTP
    /// client sends. Returns the HTTP status and the parsed body.
    async fn rpc(app: &Router, path: &str, key: Option<&str>, body: Value) -> (StatusCode, Value) {
        let mut req = Request::builder()
            .method("POST")
            .uri(path)
            .header("host", "localhost")
            .header("content-type", "application/json")
            .header("accept", "application/json, text/event-stream");
        if let Some(k) = key {
            req = req.header("x-api-key", k);
        }
        let req = req.body(Body::from(body.to_string())).expect("request");
        let res = app.clone().oneshot(req).await.expect("call");
        let status = res.status();
        let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
            .await
            .expect("body");
        (
            status,
            serde_json::from_slice(&bytes).unwrap_or(Value::Null),
        )
    }

    fn msg(id: u64, method: &str, params: Value) -> Value {
        json!({ "jsonrpc": "2.0", "id": id, "method": method, "params": params })
    }

    fn initialize() -> Value {
        msg(
            1,
            "initialize",
            json!({
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": { "name": "test", "version": "0.0.1" }
            }),
        )
    }

    /// The tool names `tools/list` returned, which rmcp sorts.
    fn tool_names(result: &Value) -> Vec<String> {
        result["tools"]
            .as_array()
            .expect("tools")
            .iter()
            .map(|t| t["name"].as_str().expect("name").to_string())
            .collect()
    }

    /// Serve the router on an ephemeral port. The real-client test needs a
    /// socket rather than `oneshot`, because both the transport and the client
    /// negotiate real HTTP.
    async fn serve(app: Router) -> String {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind");
        let addr = listener.local_addr().expect("addr");
        tokio::spawn(async move {
            let _ = axum::serve(listener, app).await;
        });
        format!("http://{addr}")
    }

    /// A real MCP client config, keyed like any other caller. `with_uri`
    /// leaves `allow_stateless` at its default, which this server needs: it
    /// never issues a session id. Returning the config rather than the
    /// transport keeps the reqwest-parameterised transport type unnamed.
    fn mcp_config(url: &str, key: &str) -> StreamableHttpClientTransportConfig {
        let mut headers = HashMap::new();
        headers.insert(
            HeaderName::from_static("x-api-key"),
            HeaderValue::from_str(key).expect("header value"),
        );
        StreamableHttpClientTransportConfig::with_uri(url).custom_headers(headers)
    }

    /// Connect a real MCP client to `url` with `key`.
    macro_rules! mcp_client {
        ($url:expr, $key:expr) => {
            ().serve(StreamableHttpClientTransport::from_config(mcp_config(
                $url, $key,
            )))
            .await
        };
    }

    /// The tool names a real client's `tools/list` returned.
    fn tool_names_of(list: &rmcp::model::ListToolsResult) -> Vec<String> {
        list.tools.iter().map(|t| t.name.to_string()).collect()
    }

    /// Both surfaces are gated: a request with no key is refused by `verify_key`
    /// before the transport ever sees a JSON-RPC message.
    #[tokio::test]
    async fn both_surfaces_are_gated() {
        let app = app().await;
        for path in [CATALOG, ADMIN] {
            let (status, _) = rpc(&app, path, None, msg(1, "tools/list", Value::Null)).await;
            assert_eq!(status, StatusCode::UNAUTHORIZED, "{path} needs a key");
        }
    }

    /// The URL, not the tool body, is the first gate on administration: a
    /// verified consumer key never reaches the admin transport.
    #[tokio::test]
    async fn a_consumer_key_cannot_reach_the_admin_surface() {
        let app = app().await;
        let (status, _) = rpc(&app, ADMIN, Some("reader.secret"), initialize()).await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        let (status, _) = rpc(&app, ADMIN, Some("admin.secret"), initialize()).await;
        assert_eq!(status, StatusCode::OK, "manage:keys opens the surface");
    }

    #[tokio::test]
    async fn a_client_negotiates_the_catalog_surface() {
        let app = app().await;
        let (status, init) = rpc(&app, CATALOG, Some("reader.secret"), initialize()).await;
        assert_eq!(status, StatusCode::OK, "handshake: {init}");
        assert_eq!(init["result"]["serverInfo"]["name"], "utmelab-api");
        // rmcp negotiates downward: asking for a handshake version gets it
        // back, never the newest version, which has no `initialize`.
        assert_eq!(init["result"]["protocolVersion"], "2025-06-18");
        assert!(
            init["result"]["capabilities"]["tools"].is_object(),
            "{init}"
        );
        assert!(
            init["result"]["capabilities"]["resources"].is_object(),
            "{init}"
        );

        let (_, tools) = rpc(
            &app,
            CATALOG,
            Some("reader.secret"),
            msg(2, "tools/list", Value::Null),
        )
        .await;
        assert_eq!(
            tool_names(&tools["result"]),
            ["assemble_paper", "score_paper"],
            "the catalog surface lists only the actions a read key may call"
        );

        let (_, resources) = rpc(
            &app,
            CATALOG,
            Some("reader.secret"),
            msg(3, "resources/list", Value::Null),
        )
        .await;
        assert_eq!(
            resources["result"]["resources"]
                .as_array()
                .expect("resources")
                .len(),
            7
        );

        let (_, templates) = rpc(
            &app,
            CATALOG,
            Some("reader.secret"),
            msg(4, "resources/templates/list", Value::Null),
        )
        .await;
        assert_eq!(
            templates["result"]["resourceTemplates"]
                .as_array()
                .expect("templates")
                .len(),
            12
        );
    }

    /// Listing and calling read the same scope declaration: a tool the caller
    /// cannot call is not advertised, so the surface never offers a door that
    /// will not open.
    #[tokio::test]
    async fn tools_list_hides_what_the_caller_cannot_call() {
        let app = app().await;

        let (_, writer) = rpc(
            &app,
            CATALOG,
            Some("writer.secret"),
            msg(1, "tools/list", Value::Null),
        )
        .await;
        assert_eq!(
            tool_names(&writer["result"]),
            ["file_report"],
            "a report writer sees only the report write"
        );

        let (_, nobody) = rpc(
            &app,
            CATALOG,
            Some("nobody.secret"),
            msg(2, "tools/list", Value::Null),
        )
        .await;
        assert!(
            nobody["result"]["tools"]
                .as_array()
                .expect("tools")
                .is_empty(),
            "a key with no scope is offered no action: {nobody}"
        );
    }

    /// The requirement is on the wire, namespaced, next to the tool that needs
    /// it, so a client can check before it calls.
    #[tokio::test]
    async fn a_tool_advertises_the_scope_it_needs() {
        let app = app().await;
        let (_, listed) = rpc(
            &app,
            CATALOG,
            Some("writer.secret"),
            msg(1, "tools/list", Value::Null),
        )
        .await;
        let file_report = listed["result"]["tools"]
            .as_array()
            .expect("tools")
            .iter()
            .find(|t| t["name"] == "file_report")
            .expect("file_report is listed");
        assert_eq!(
            file_report["_meta"]["io.utmelab/requiredScope"], "write:reports",
            "{file_report}"
        );
    }

    /// No tool argument advertises a nullable `type` array. schemars spells
    /// `Option<T>` that way; it is legal, but a client that maps onto a
    /// single-`type` dialect may reject the whole tool, so the schema is kept
    /// to plain types.
    #[tokio::test]
    async fn no_tool_argument_advertises_a_nullable_type() {
        let app = app().await;
        for (path, key) in [
            (CATALOG, "reader.secret"),
            (CATALOG, "writer.secret"),
            (ADMIN, "admin.secret"),
        ] {
            let (_, listed) = rpc(&app, path, Some(key), msg(1, "tools/list", Value::Null)).await;
            for tool in listed["result"]["tools"].as_array().expect("tools") {
                let properties = tool["inputSchema"]["properties"]
                    .as_object()
                    .expect("properties");
                for (name, property) in properties {
                    assert!(
                        property["type"].is_string(),
                        "{} must render a plain type for {name}: {property}",
                        tool["name"]
                    );
                }
            }
        }
    }

    /// The catalog surface cannot even name an admin tool, whatever key asks.
    /// The split is the URL, not a scope check: an admin key on `/mcp` still
    /// sees only catalog tools, and the admin router is a separate value that
    /// `tools()` never hands to `list_tools`.
    #[tokio::test]
    async fn the_catalog_surface_never_names_an_admin_tool() {
        let app = app().await;
        const ADMIN_TOOLS: [&str; 4] = ["create_key", "revoke_key", "rotate_key", "unrevoke_key"];
        for key in [
            "reader.secret",
            "writer.secret",
            "nobody.secret",
            // Holds `manage:keys`, and still must not see them here.
            "admin.secret",
        ] {
            let (_, listed) =
                rpc(&app, CATALOG, Some(key), msg(1, "tools/list", Value::Null)).await;
            let names = tool_names(&listed["result"]);
            for admin_tool in ADMIN_TOOLS {
                assert!(
                    !names.iter().any(|name| name == admin_tool),
                    "{key} saw {admin_tool} on the catalog surface: {names:?}"
                );
            }
        }
    }

    /// The admin surface is tools-only: no resources are advertised or served,
    /// so it cannot be used to read the catalog.
    #[tokio::test]
    async fn the_admin_surface_serves_tools_only() {
        let app = app().await;
        let (_, init) = rpc(&app, ADMIN, Some("admin.secret"), initialize()).await;
        assert_eq!(init["result"]["serverInfo"]["name"], "utmelab-api-admin");
        assert!(
            init["result"]["capabilities"]["tools"].is_object(),
            "{init}"
        );
        assert!(
            init["result"]["capabilities"]["resources"].is_null(),
            "no resources capability: {init}"
        );

        let (_, tools) = rpc(
            &app,
            ADMIN,
            Some("admin.secret"),
            msg(2, "tools/list", Value::Null),
        )
        .await;
        assert_eq!(
            tool_names(&tools["result"]),
            ["create_key", "revoke_key", "rotate_key", "unrevoke_key"]
        );

        let (_, resources) = rpc(
            &app,
            ADMIN,
            Some("admin.secret"),
            msg(3, "resources/list", Value::Null),
        )
        .await;
        assert!(resources["result"]["resources"]
            .as_array()
            .expect("resources")
            .is_empty());

        let (_, refused) = rpc(
            &app,
            ADMIN,
            Some("admin.secret"),
            msg(
                4,
                "resources/read",
                json!({ "uri": "utmelab://catalog/exams" }),
            ),
        )
        .await;
        assert_eq!(
            refused["error"]["code"], -32601,
            "method not found: {refused}"
        );
    }

    /// An admin tool is not merely refused on the catalog surface; it is not
    /// there. The consumer key gets rmcp's own "tool not found".
    #[tokio::test]
    async fn an_admin_tool_is_absent_from_the_catalog_surface() {
        let app = app().await;
        let (_, refused) = rpc(
            &app,
            CATALOG,
            Some("reader.secret"),
            msg(
                1,
                "tools/call",
                json!({ "name": "rotate_key", "arguments": { "prefix": "ghost" } }),
            ),
        )
        .await;
        assert_eq!(refused["error"]["message"], "tool not found", "{refused}");
    }

    /// The no-drift proof, the same shape the HTTP sweep uses: a resource and
    /// its route are one implementation, so their answers are equal.
    #[tokio::test]
    async fn a_resource_answers_what_its_http_twin_answers() {
        let app = app().await;
        let (_, read) = rpc(
            &app,
            CATALOG,
            Some("reader.secret"),
            msg(
                1,
                "resources/read",
                json!({ "uri": "utmelab://catalog/exams" }),
            ),
        )
        .await;
        let text = read["result"]["contents"][0]["text"]
            .as_str()
            .expect("resource text");
        let via_mcp: Value = serde_json::from_str(text).expect("resource text is JSON");

        let (status, via_http) =
            call(app, "GET", "/api/v1/exams", Some("reader.secret"), None).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(via_mcp, via_http, "resource and route must agree");
    }

    /// Identity is not authorization on this surface either: a read key is
    /// refused `file_report`, and the refusal carries the same machine code
    /// HTTP's 403 body would. The scope enforced is the one the tool declared,
    /// the same `write:reports` the HTTP route demands.
    #[tokio::test]
    async fn a_tool_checks_the_same_scope_http_checks() {
        let app = app().await;
        let (status, refused) = rpc(
            &app,
            CATALOG,
            Some("reader.secret"),
            msg(
                1,
                "tools/call",
                json!({
                    "name": "file_report",
                    "arguments": {
                        "target_type": "question",
                        "target_id": "q1",
                        "reason": "other"
                    }
                }),
            ),
        )
        .await;
        assert_eq!(
            status,
            StatusCode::OK,
            "a scope refusal is a JSON-RPC error, not a transport one: {refused}"
        );
        assert_eq!(refused["error"]["data"]["code"], "forbidden", "{refused}");
    }

    /// The admin surface's own tools run behind its scope: an unknown prefix
    /// means the admin key cleared the gate and the store answered.
    #[tokio::test]
    async fn an_admin_key_alone_reaches_the_admin_tools() {
        let app = app().await;
        let (_, not_found) = rpc(
            &app,
            ADMIN,
            Some("admin.secret"),
            msg(
                1,
                "tools/call",
                json!({ "name": "rotate_key", "arguments": { "prefix": "ghost" } }),
            ),
        )
        .await;
        assert_eq!(
            not_found["error"]["data"]["code"], "not_found",
            "{not_found}"
        );
    }

    /// The admin surface can hand out a consumer key: the tool dispatches into
    /// the store, which derives the grant from the tier and refuses one it does
    /// not know. (The grant itself is pinned in the store tests; the test
    /// replica is offline, so a valid call would stop at the failed push.)
    #[tokio::test]
    async fn an_admin_key_reaches_the_create_key_tool() {
        let app = app().await;
        let (_, refused) = rpc(
            &app,
            ADMIN,
            Some("admin.secret"),
            msg(
                1,
                "tools/call",
                json!({ "name": "create_key", "arguments": { "tier": "root", "owner": "utmelab-app" } }),
            ),
        )
        .await;
        assert_eq!(
            refused["error"]["data"]["code"], "bad_request",
            "the store validates the tier behind the tool: {refused}"
        );
    }

    /// What the hand-written bodies cannot prove: a real MCP client
    /// (`rmcp::Client` over rmcp's own Streamable HTTP transport) drives the
    /// served surface across a real socket, so the handshake, the schemas, and
    /// the responses are checked by a client that is not ours.
    #[tokio::test]
    async fn a_real_mcp_client_drives_the_served_surface() {
        let app = app().await;
        let base = serve(app.clone()).await;

        let reader =
            mcp_client!(&format!("{base}/mcp"), "reader.secret").expect("handshake against /mcp");

        assert_eq!(
            tool_names_of(&reader.list_tools(None).await.expect("list tools")),
            ["assemble_paper", "score_paper"],
            "listing is scope-filtered for a real client too"
        );

        let refused = reader
            .call_tool(
                CallToolRequestParams::new("file_report").with_arguments(
                    json!({
                        "target_type": "question",
                        "target_id": "q1",
                        "reason": "other"
                    })
                    .as_object()
                    .expect("object")
                    .clone(),
                ),
            )
            .await
            .expect_err("file_report needs write:reports");
        let rmcp::ServiceError::McpError(err) = refused else {
            panic!("expected an MCP error, got {refused:?}");
        };
        assert_eq!(
            err.data.as_ref().and_then(|d| d["code"].as_str()),
            Some("forbidden"),
            "the refusal carries the machine code: {err}"
        );

        let read = reader
            .read_resource(ReadResourceRequestParams::new("utmelab://catalog/exams"))
            .await
            .expect("read exams");
        let text = match &read.contents[0] {
            ResourceContents::TextResourceContents { text, .. } => text.clone(),
            other => panic!("expected text contents, got {other:?}"),
        };
        let via_mcp: Value = serde_json::from_str(&text).expect("resource text is JSON");
        let (status, via_http) =
            call(app, "GET", "/api/v1/exams", Some("reader.secret"), None).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(via_mcp, via_http, "resource and route must agree");

        let admin = mcp_client!(&format!("{base}/mcp/admin"), "admin.secret")
            .expect("handshake against /mcp/admin");
        assert_eq!(
            tool_names_of(&admin.list_tools(None).await.expect("list tools")),
            ["create_key", "revoke_key", "rotate_key", "unrevoke_key"]
        );

        assert!(
            mcp_client!(&format!("{base}/mcp/admin"), "reader.secret").is_err(),
            "a key without manage:keys cannot open the admin transport"
        );
    }
}
