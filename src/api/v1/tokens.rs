//! Short-lived client credentials. A developer's backend presents its secret
//! key here and hands the returned token to a browser, desktop, or mobile
//! client, so the secret itself never ships to the client. The token is
//! read-only, expires quickly, and is billed to the parent key's quota.
//!
//! The endpoint is a write (it inserts a token row), so `api::router` mounts it
//! with `reports` under the write budget, outside the read group. It is also
//! behind `verify_key`, which means a token cannot mint another token: the
//! handler refuses anything that is not a secret.

use axum::{extract::State, routing::post, Json, Router};

use crate::{
    auth::{api_key::AuthedKey, Credential, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

/// `POST /v1/tokens`: mint a short-lived token for a client app.
#[utoipa::path(
    post,
    path = "/api/v1/tokens",
    tag = "account",
    operation_id = "mintAccessToken",
    summary = "Mint a short-lived token for a client app.",
    description = "Requires a secret key with `read:catalog`. The returned token can read the \
catalog and nothing else, expires in at most 15 minutes, cannot mint another token, and is \
billed to the presenting key's quota.",
    request_body = core::models::TokenRequest,
    responses(
        (status = 200, body = core::models::AccessToken),
        core::models::ApiErrorResponses,
    ),
    security(("ApiKeyAuth" = [])),
)]
pub async fn mint(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    body: Option<Json<core::models::TokenRequest>>,
) -> Result<Json<core::models::AccessToken>, AppError> {
    // A token is a bearer credential for clients; only the long-lived secret
    // may create one. This is the boundary that stops a stolen token from
    // refreshing itself forever.
    if auth.credential != Credential::Secret {
        return Err(AppError::Forbidden);
    }
    auth.require(SCOPE_READ_CATALOG)?;
    if !s.limiter.check_mint(&auth.key_id).await {
        return Err(AppError::RateLimited);
    }
    let expires_in = core::accounts::token_lifetime(body.and_then(|Json(b)| b.expires_in));
    let (access_token, scopes) = store::accounts::mint_token(&s, &auth, expires_in).await?;
    Ok(Json(core::models::AccessToken {
        access_token,
        token_type: "Bearer".to_string(),
        expires_in,
        scopes,
    }))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/tokens", post(mint))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::state::{AppState, DbState};
    use crate::testing::{
        api_schema, bank_schema, call, call_with_headers, connect, expire_token, issue_key,
        replica, revoke_key, state,
    };
    use axum::extract::FromRef;
    use axum::http::StatusCode;
    use serde_json::Value;

    /// Offline replica with a read/write key, a write-only key, and one real
    /// question. The write-only key proves the mint gate is the read scope, not
    /// merely "any key". The reader holds both scopes, so the tests can prove
    /// the minted token is narrower than its parent rather than merely equal
    /// to a read-only fixture.
    async fn seeded_app_and_state() -> (axum::Router, AppState) {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &[
                "subjects",
                "topics",
                "questions",
                "verifications",
                "subtopics",
                "passages",
            ],
        )
        .await;
        conn.execute(
            "INSERT INTO subjects VALUES ('physics','JAMB','Physics',0,40,'[]',NULL,NULL)",
            (),
        )
        .await
        .expect("insert subject");
        conn.execute(
            "INSERT INTO questions VALUES ('q1','JAMB','physics',2025,'past_paper','What is 2+2?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"4\",\"inline\":[]}}]','a',NULL,NULL,NULL,'{\"key_point\":{\"text\":\"addition\",\"inline\":[]},\"body\":{\"text\":\"2+2=4\",\"inline\":[]}}',1.0,2,'h1')",
            (),
        )
        .await
        .expect("insert question");
        conn.execute(
            "INSERT INTO verifications VALUES ('v1','q1','human','pass','[\"answer\",\"explanation\"]','review',NULL,'h1','2026-01-01T00:00:00Z')",
            (),
        )
        .await
        .expect("insert verification");
        issue_key(
            &conn,
            "reader.secret",
            "commercial",
            "read:catalog,write:reports",
            false,
        )
        .await;
        issue_key(&conn, "writer.secret", "commercial", "write:reports", false).await;
        let st = state(db);
        let app = crate::routes::router(st.clone(), &crate::config::Config::default());
        (app, st)
    }

    async fn seeded_app() -> axum::Router {
        seeded_app_and_state().await.0
    }

    async fn mint(app: axum::Router, key: &str, body: Option<&str>) -> (StatusCode, Value) {
        call(app, "POST", "/api/v1/tokens", Some(key), body).await
    }

    fn token_of(body: &Value) -> String {
        body["access_token"]
            .as_str()
            .expect("a minted token")
            .to_string()
    }

    #[tokio::test]
    async fn a_secret_mints_a_read_only_client_token() {
        let app = seeded_app().await;
        let (status, body) = mint(app, "reader.secret", None).await;
        assert_eq!(status, StatusCode::OK, "{body}");
        assert!(token_of(&body).starts_with("tok_"), "{body}");
        assert_eq!(body["token_type"], "Bearer");
        assert_eq!(body["expires_in"], 300, "the default is five minutes");
        assert_eq!(body["scopes"], serde_json::json!(["read:catalog"]));
    }

    /// The token is a real credential on the real catalog route: it carries
    /// `read:catalog` through the gate, the scope check, the store query, and
    /// the page envelope. It also resolves to the parent key for identity.
    #[tokio::test]
    async fn the_token_reads_the_catalog_as_its_parent() {
        let app = seeded_app().await;
        let (_, body) = mint(app.clone(), "reader.secret", None).await;
        let bearer = format!("Bearer {}", token_of(&body));
        let (status, _, page) = call_with_headers(
            app.clone(),
            "GET",
            "/api/v1/questions",
            None,
            &[("authorization", bearer.as_str())],
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{page}");
        assert_eq!(page["total_records"], 1);
        assert_eq!(page["questions"][0]["id"], "q1");
        assert!(
            page["questions"][0].get("answer").is_none(),
            "the token gets the same answer withholding as any reader"
        );

        let (status, _, me) = call_with_headers(
            app,
            "GET",
            "/api/v1/keys/me",
            None,
            &[("authorization", bearer.as_str())],
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{me}");
        assert_eq!(me["prefix"], "reader", "the parent key is the identity");
        assert_eq!(me["admin"], false);
        assert_eq!(me["scopes"], serde_json::json!(["read:catalog"]));
    }

    /// The parent holds `write:reports`, the token does not. A client
    /// credential must not inherit a write it was never granted.
    #[tokio::test]
    async fn a_token_cannot_write_even_when_its_parent_can() {
        let app = seeded_app().await;
        let (_, body) = mint(app.clone(), "reader.secret", None).await;
        let bearer = format!("Bearer {}", token_of(&body));
        let (status, _, refused) = call_with_headers(
            app,
            "POST",
            "/api/v1/report",
            None,
            &[("authorization", bearer.as_str())],
            Some(r#"{"target_type":"question","target_id":"q1","reason":"other"}"#),
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{refused}");
    }

    /// Both credentials on one request is refused on the real read route, not
    /// only at a probe router.
    #[tokio::test]
    async fn both_headers_are_refused_on_the_read_route() {
        let app = seeded_app().await;
        let (_, body) = mint(app.clone(), "reader.secret", None).await;
        let bearer = format!("Bearer {}", token_of(&body));
        let (status, _, _) = call_with_headers(
            app,
            "GET",
            "/api/v1/questions",
            Some("reader.secret"),
            &[("authorization", bearer.as_str())],
            None,
        )
        .await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
    }

    /// Expiry and parent revocation are enforced on the read route, not only in
    /// the store: a token that worked a moment ago stops working.
    #[tokio::test]
    async fn an_expired_or_orphaned_token_is_refused_on_the_read_route() {
        let (app, st) = seeded_app_and_state().await;
        let db = DbState::from_ref(&st);
        let (_, body) = mint(app.clone(), "reader.secret", None).await;
        let token = token_of(&body);
        let bearer = format!("Bearer {token}");

        expire_token(&db, &token).await;
        assert_eq!(
            call_with_headers(
                app.clone(),
                "GET",
                "/api/v1/questions",
                None,
                &[("authorization", bearer.as_str())],
                None
            )
            .await
            .0,
            StatusCode::UNAUTHORIZED,
            "an expired token must not read"
        );

        let (_, body) = mint(app.clone(), "reader.secret", None).await;
        let bearer = format!("Bearer {}", token_of(&body));
        revoke_key(&db, "reader").await;
        assert_eq!(
            call_with_headers(
                app,
                "GET",
                "/api/v1/questions",
                None,
                &[("authorization", bearer.as_str())],
                None
            )
            .await
            .0,
            StatusCode::UNAUTHORIZED,
            "revoking the parent must kill the token family"
        );
    }

    /// A token cannot mint. If it could, a leaked five-minute credential could
    /// keep itself alive indefinitely.
    #[tokio::test]
    async fn a_token_cannot_mint_another_token() {
        let app = seeded_app().await;
        let (_, body) = mint(app.clone(), "reader.secret", None).await;
        let bearer = format!("Bearer {}", token_of(&body));
        let (status, _, refused) = call_with_headers(
            app,
            "POST",
            "/api/v1/tokens",
            None,
            &[("authorization", bearer.as_str())],
            None,
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{refused}");
    }

    /// The grant is read-only, so a key that cannot read the catalog cannot
    /// mint a token that can.
    #[tokio::test]
    async fn a_key_without_the_read_scope_cannot_mint() {
        let app = seeded_app().await;
        let (status, refused) = mint(app, "writer.secret", None).await;
        assert_eq!(status, StatusCode::FORBIDDEN, "{refused}");
    }

    /// The request may name a lifetime, but the policy owns the ceiling and the
    /// response says what was actually granted.
    #[tokio::test]
    async fn the_requested_lifetime_is_clamped() {
        let app = seeded_app().await;
        let (status, body) = mint(app, "reader.secret", Some(r#"{"expires_in":86400}"#)).await;
        assert_eq!(status, StatusCode::OK, "{body}");
        assert_eq!(body["expires_in"], 900, "the ceiling is fifteen minutes");
    }

    /// MCP is a server and agent surface. A client token is refused there
    /// before rmcp sees a message, whatever its scopes.
    #[tokio::test]
    async fn a_client_token_is_refused_on_mcp() {
        let app = seeded_app().await;
        let (_, body) = mint(app.clone(), "reader.secret", None).await;
        let bearer = format!("Bearer {}", token_of(&body));
        let (status, _, _) = call_with_headers(
            app,
            "POST",
            "/mcp",
            None,
            &[("authorization", bearer.as_str())],
            None,
        )
        .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
    }
}
