//! MCP surface: the keyed HTTP surface under a tool-call vocabulary.
//!
//! A read is a resource (`GET /mcp/resources/<tail>`, `resources.rs`); an
//! action is a tool (`POST /mcp/tools/<verb>_<noun>`, `tools.rs`). Every route
//! but the two admin tools mounts the same handler its `/api/v1` twin does, so
//! the surfaces cannot drift and no scope, gate, or rendered shape is written
//! twice. Same `verify_key` gate as HTTP (`api::router`); do not add a second
//! auth for a capability HTTP already guards.
//!
//! This is not a JSON-RPC MCP server: the transport is plain HTTP, keyed, with
//! one route per operation. The vocabulary is the MCP one so a client that
//! speaks tools/resources can be pointed at it.

pub mod resources;
pub mod tools;

use axum::{middleware::from_fn_with_state, Router};

use crate::{auth::api_key::verify_key, config::Config, state::AppState};

pub fn router(state: AppState, cfg: &Config) -> Router<AppState> {
    // Same split as `api`: `verify_key` rides inside the budget of the group
    // it guards, so the gate is bounded like the work behind it.
    let reads = resources::routes()
        .layer(from_fn_with_state(state.clone(), verify_key))
        .layer(cfg.fast_timeout());
    let actions = tools::routes()
        .layer(from_fn_with_state(state.clone(), verify_key))
        .layer(cfg.slow_timeout());
    reads.merge(actions).with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::testing::{api_schema, bank_schema, call, connect, issue_key, replica, state};
    use axum::http::StatusCode;

    /// A replica with one exam, so a resource has something to answer and the
    /// two surfaces can be compared on real output.
    async fn seeded() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["exams"]).await;
        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','JAMB','[\"NG\"]','live',0,4,120,'[]')",
            (),
        )
        .await
        .expect("insert exam");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// MCP mirrors HTTP by construction: each pair shares one handler, so this
    /// proves the wiring points both at it, not that two implementations agree.
    #[tokio::test]
    async fn mcp_resources_answer_what_http_answers() {
        let app = seeded().await;
        for (http, mcp) in [
            ("/api/v1/exams", "/mcp/resources/exams"),
            ("/api/v1/meta/tables", "/mcp/resources/meta/tables"),
            ("/api/v1/keys/me", "/mcp/resources/keys/me"),
            ("/api/v1/questions", "/mcp/resources/questions"),
        ] {
            let (hs, hv) = call(app.clone(), "GET", http, Some("reader.secret"), None).await;
            let (ms, mv) = call(app.clone(), "GET", mcp, Some("reader.secret"), None).await;
            assert_eq!(hs, ms, "status for {http} vs {mcp}");
            assert_eq!(hv, mv, "body for {http} vs {mcp}");
        }
    }

    /// The tool half: a write tool mounts the HTTP write handler, so the scope
    /// gate answers the same from either path. A read key is refused by both.
    #[tokio::test]
    async fn mcp_tools_share_the_http_write_handler() {
        let app = seeded().await;
        let body = r#"{"target_type":"question","target_id":"q1","reason":"other"}"#;
        let (hs, _) = call(
            app.clone(),
            "POST",
            "/api/v1/report",
            Some("reader.secret"),
            Some(body),
        )
        .await;
        let (ms, _) = call(
            app,
            "POST",
            "/mcp/tools/file_report",
            Some("reader.secret"),
            Some(body),
        )
        .await;
        assert_eq!(hs, StatusCode::FORBIDDEN);
        assert_eq!(ms, hs, "the tool must gate like the route");
    }
}
