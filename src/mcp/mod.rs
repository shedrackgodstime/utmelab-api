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

    /// MCP mirrors HTTP by construction: every HTTP read has an MCP resource
    /// twin at `/mcp/resources/<tail>`. Deriving the twin from the HTTP read
    /// list and comparing status + body proves the wiring points both at the
    /// same handler — a read added without its resource fails here.
    #[tokio::test]
    async fn mcp_resources_answer_what_http_answers() {
        let app = seeded().await;
        let http_reads: &[(&str, &str)] = &[
            ("GET", "/api/v1/exams"),
            ("GET", "/api/v1/exams/JAMB/subjects"),
            ("GET", "/api/v1/exams/JAMB/papers"),
            ("GET", "/api/v1/subjects/JAMB/physics"),
            ("GET", "/api/v1/subjects/JAMB/physics/syllabus"),
            ("GET", "/api/v1/subjects/JAMB/physics/coverage"),
            ("GET", "/api/v1/topics/JAMB/physics/mechanics"),
            ("GET", "/api/v1/blueprints/JAMB/physics"),
            ("GET", "/api/v1/passages/p1"),
            ("GET", "/api/v1/novels"),
            ("GET", "/api/v1/novels/lekki"),
            ("GET", "/api/v1/novels/lekki/questions"),
            ("GET", "/api/v1/questions"),
            ("GET", "/api/v1/questions/q1"),
            ("GET", "/api/v1/keys/me"),
            ("GET", "/api/v1/meta/tables"),
            ("GET", "/api/v1/meta/rows/exams"),
        ];
        for (method, http) in http_reads {
            let tail = http.strip_prefix("/api/v1/").expect("an api/v1 path");
            let mcp = format!("/mcp/resources/{tail}");
            let (hs, hv) = call(app.clone(), method, http, Some("reader.secret"), None).await;
            let (ms, mv) = call(app.clone(), method, &mcp, Some("reader.secret"), None).await;
            assert_eq!(hs, ms, "status for {http} vs {mcp}: {hs} vs {ms}");
            assert_eq!(hv, mv, "body for {http} vs {mcp}: {hv} vs {mv}");
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

    /// MCP-only admin tools: `rotate_key` mounts `store::accounts::rotate_key`.
    /// An admin key rotates; a read key is refused.
    #[tokio::test]
    async fn mcp_rotate_key_tool() {
        // App with a reader key and an admin key, plus a key to rotate.
        let app = {
            let db = replica().await;
            let conn = connect(&db).await;
            api_schema(&conn).await;
            issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
            issue_key(&conn, "admin.secret", "admin", "manage:keys", false).await;
            issue_key(
                &conn,
                "to_rotate.secret",
                "commercial",
                "read:catalog",
                false,
            )
            .await;
            crate::routes::router(state(db), &crate::config::Config::default())
        };

        // A read key cannot rotate.
        let (ms, _) = call(
            app.clone(),
            "POST",
            "/mcp/tools/rotate_key",
            Some("reader.secret"),
            Some(r#"{"prefix":"to_rotate"}"#),
        )
        .await;
        assert_eq!(ms, StatusCode::FORBIDDEN, "read key cannot rotate");

        // An unknown prefix is not found.
        let (ms, _) = call(
            app.clone(),
            "POST",
            "/mcp/tools/rotate_key",
            Some("admin.secret"),
            Some(r#"{"prefix":"ghost"}"#),
        )
        .await;
        assert_eq!(ms, StatusCode::NOT_FOUND, "unknown prefix is not found");

        // A valid rotate hits the offline push: 502 upstream, same as every
        // write in the test harness. The store test covers the local commit.
        let (ms, _) = call(
            app,
            "POST",
            "/mcp/tools/rotate_key",
            Some("admin.secret"),
            Some(r#"{"prefix":"to_rotate"}"#),
        )
        .await;
        assert_eq!(ms, StatusCode::BAD_GATEWAY, "push fails offline");
    }
}
