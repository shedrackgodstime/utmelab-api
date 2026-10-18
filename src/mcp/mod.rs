//! MCP surface: a real JSON-RPC 2.0 server over Streamable HTTP at `/mcp`.
//!
//! `rmcp` owns the wire: JSON-RPC framing, capability negotiation, protocol
//! version negotiation, and the resource and tool vocabulary. This module owns
//! only the two things rmcp cannot know — this repo's identity and its
//! catalog. Tools live in [`server`]; resource URIs live in [`resources`].
//!
//! Identity is the key the HTTP surface already uses. `verify_key` (the same
//! layer `api/v1` mounts) stashes the [`Auth`] in the request extensions before
//! rmcp sees the message; the transport copies the request `Parts` into every
//! JSON-RPC message, so a handler reads its caller from `context.extensions`
//! and checks the same scopes HTTP checks. One identity, one scope vocabulary,
//! one gate.
//!
//! The server is stateless: `legacy_session_mode(false)` keeps every request on
//! the stateless path, so no `Mcp-Session-Id` is minted and no protocol state
//! outlives a request. That is what lets one shared server instance serve every
//! caller without ever holding someone else's identity.
//!
//! [`Auth`]: crate::auth::Auth

pub mod resources;
pub mod server;

pub use server::McpServer;

use std::sync::Arc;

use axum::{extract::FromRef, middleware::from_fn_with_state, Router};
use rmcp::{
    model::ErrorCode,
    transport::streamable_http_server::{
        session::local::LocalSessionManager, StreamableHttpServerConfig, StreamableHttpService,
    },
    ErrorData,
};

use crate::{
    auth::api_key::verify_key,
    config::Config,
    error::AppError,
    state::{AppState, DbState},
};

pub fn router(state: AppState, cfg: &Config) -> Router<AppState> {
    let db = DbState::from_ref(&state);
    let mcp = StreamableHttpService::new(
        move || Ok(McpServer::new(db.clone())),
        Arc::new(LocalSessionManager::default()),
        StreamableHttpServerConfig::default()
            // Stateless: each request carries its own identity and its own
            // protocol metadata, so no session outlives a request.
            .with_legacy_session_mode(false)
            // Prefer plain JSON over SSE for request/response calls. Nothing
            // here emits a notification mid-call, so SSE would only add a frame
            // to parse for no gain.
            .with_json_response(true)
            .with_sse_keep_alive(None)
            // Host-header validation is a local-development guard against DNS
            // rebinding. This server is keyed on every surface and answers one
            // public name behind a proxy, so the key is the boundary; a
            // localhost allowlist would reject real traffic and protect
            // nothing.
            .disable_allowed_hosts(),
    );
    Router::new()
        .nest_service("/mcp", mcp)
        // Same gate as HTTP; a tool can push to the cloud (a report, a key
        // rotation), so it takes the write budget.
        .layer(from_fn_with_state(state.clone(), verify_key))
        .layer(cfg.slow_timeout())
        .with_state(state)
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
    use axum::{
        body::Body,
        http::{Request, StatusCode},
        Router,
    };
    use serde_json::{json, Value};
    use tower::ServiceExt;

    use crate::testing::{api_schema, bank_schema, call, connect, issue_key, replica, state};

    /// A replica the surface can answer from: one exam, a read key, an admin
    /// key.
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
        issue_key(&conn, "admin.secret", "admin", "manage:keys", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// One JSON-RPC message POSTed to `/mcp` with the headers a Streamable HTTP
    /// client sends. Returns the HTTP status and the parsed body.
    async fn rpc(app: &Router, key: Option<&str>, body: Value) -> (StatusCode, Value) {
        let mut req = Request::builder()
            .method("POST")
            .uri("/mcp")
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

    /// The gate is the surface's, not rmcp's: a request with no key is refused
    /// by `verify_key` before the transport ever sees a JSON-RPC message.
    #[tokio::test]
    async fn the_surface_is_gated_before_it_speaks_json_rpc() {
        let app = app().await;
        let (status, _) = rpc(&app, None, msg(1, "tools/list", Value::Null)).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
    }

    #[tokio::test]
    async fn a_client_negotiates_then_lists_tools_and_resources() {
        let app = app().await;
        let (status, init) = rpc(
            &app,
            Some("reader.secret"),
            msg(
                1,
                "initialize",
                json!({
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": { "name": "test", "version": "0.0.1" }
                }),
            ),
        )
        .await;
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
            Some("reader.secret"),
            msg(2, "tools/list", Value::Null),
        )
        .await;
        let names: Vec<&str> = tools["result"]["tools"]
            .as_array()
            .expect("tools")
            .iter()
            .map(|t| t["name"].as_str().expect("name"))
            .collect();
        for expected in [
            "file_report",
            "assemble_paper",
            "score_paper",
            "revoke_key",
            "unrevoke_key",
            "rotate_key",
        ] {
            assert!(names.contains(&expected), "missing {expected}: {names:?}");
        }

        let (_, resources) = rpc(
            &app,
            Some("reader.secret"),
            msg(3, "resources/list", Value::Null),
        )
        .await;
        assert_eq!(
            resources["result"]["resources"]
                .as_array()
                .expect("resources")
                .len(),
            5
        );

        let (_, templates) = rpc(
            &app,
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

    /// The no-drift proof, the same shape the HTTP sweep uses: a resource and
    /// its route are one implementation, so their answers are equal, not merely
    /// similar.
    #[tokio::test]
    async fn a_resource_answers_what_its_http_twin_answers() {
        let app = app().await;
        let (_, read) = rpc(
            &app,
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
    /// HTTP's 403 body would.
    #[tokio::test]
    async fn a_tool_checks_the_same_scope_http_checks() {
        let app = app().await;
        let (status, refused) = rpc(
            &app,
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

    #[tokio::test]
    async fn an_admin_key_alone_reaches_the_admin_tools() {
        let app = app().await;
        // An unknown prefix means the admin key cleared the scope gate and the
        // store answered, so the tool really ran.
        let (_, not_found) = rpc(
            &app,
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
}
