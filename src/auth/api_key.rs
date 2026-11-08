//! `x-api-key` and `Authorization: Bearer` wire. One gate, one identity for
//! `api` + `mcp`: a long-lived secret is presented in `x-api-key`, a
//! short-lived client token in `Authorization: Bearer tok_...`. Exactly one
//! credential per request; both is a refusal, never a precedence guess.
//! Verification SQL lives in `store::accounts`.

use axum::{
    body::Body,
    extract::{FromRef, FromRequestParts, State},
    http::{
        header::{HeaderMap, HeaderName, AUTHORIZATION},
        request::Parts,
        Request,
    },
    middleware::Next,
    response::Response,
};

use crate::{
    auth::Auth,
    error::AppError,
    state::{AppState, DbState},
    store,
};

pub const KEY_HEADER: &str = "x-api-key";
/// Prefix every minted client token carries, so a token can never be mistaken
/// for a long-lived key and vice versa.
pub const TOKEN_PREFIX: &str = "tok_";

/// The gate: verify the presented credential and stash its [`Auth`] in the
/// request extensions. Applied as a layer over every keyed router (`api/v1`,
/// both the read and write groups in `api::router`; `mcp`), so identity is a
/// property of the surface, not of remembering to write an extractor. A route
/// on a keyed router is gated whether or not it mentions `AuthedKey`; a route
/// that does mention it and was mounted outside one fails closed (401), never
/// open.
///
/// The per-key rate limit rides here for the same reason: it cannot be
/// forgotten either. A token is billed to its parent key, so minting more
/// tokens never buys a fresh bucket. Scope does not ride here: it differs per
/// route, so [`Auth::require`] stays one line in the handler that needs it.
pub async fn verify_key(
    State(state): State<AppState>,
    mut request: Request<Body>,
    next: Next,
) -> Result<Response, AppError> {
    let headers = request.headers();
    let key = headers
        .get(HeaderName::from_static(KEY_HEADER))
        .and_then(|v| v.to_str().ok());
    let has_authorization = headers.contains_key(AUTHORIZATION);
    if key.is_some() && has_authorization {
        return Err(AppError::Unauthorized);
    }
    let s = DbState::from_ref(&state);
    let auth = match (key, bearer_token(headers)) {
        (Some(raw), None) => store::accounts::verify_key(&s, raw).await?,
        (None, Some(token)) => store::accounts::verify_token(&s, token).await?,
        _ => return Err(AppError::Unauthorized),
    };
    if !s.limiter.check_api_key(&auth.key_id, auth.is_admin).await {
        return Err(AppError::RateLimited);
    }
    request.extensions_mut().insert(auth);
    Ok(next.run(request).await)
}

/// The token half of an `Authorization` header, if the scheme is Bearer.
/// An unusable header is `None`; the caller then fails closed because no
/// other credential is present.
fn bearer_token(headers: &HeaderMap) -> Option<&str> {
    let value = headers.get(AUTHORIZATION)?.to_str().ok()?;
    let (scheme, token) = value.split_once(' ')?;
    if !scheme.eq_ignore_ascii_case("bearer") {
        return None;
    }
    let token = token.trim();
    if token.is_empty() {
        return None;
    }
    Some(token)
}

/// Extractor: any handler taking this reads the identity [`verify_key`] put
/// in the extensions. Absent, it rejects: a keyed handler mounted off a keyed
/// router is refused, not trusted. Callers check scopes via [`Auth::require`],
/// one line per operation. Session surfaces use their own extractors; the two
/// identities never mix.
pub struct AuthedKey(pub Auth);

impl FromRequestParts<AppState> for AuthedKey {
    type Rejection = AppError;

    async fn from_request_parts(
        parts: &mut Parts,
        _state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        parts
            .extensions
            .get::<Auth>()
            .cloned()
            .map(AuthedKey)
            .ok_or(AppError::Unauthorized)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::{api_schema, call, call_with_headers, connect, issue_key, replica, state};
    use axum::{middleware::from_fn_with_state, routing::get, Router};

    /// The structural property the extractor could not give: a route that
    /// never asks for `AuthedKey` is still refused without a key, because the
    /// gate is the layer. A handler missing the extractor used to be an open
    /// route; now it is only a handler with no key in scope.
    #[tokio::test]
    async fn the_layer_gates_a_route_that_never_asks_for_identity() {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        issue_key(&conn, "live.secret", "commercial", "read:catalog", false).await;
        issue_key(&conn, "revoked.secret", "commercial", "read:catalog", true).await;
        let app: Router = Router::new()
            .route("/probe", get(|| async { "ok" }))
            .layer(from_fn_with_state(state(db), verify_key));

        assert_eq!(
            call(app.clone(), "GET", "/probe", None, None).await.0,
            axum::http::StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            call(app.clone(), "GET", "/probe", Some("revoked.secret"), None)
                .await
                .0,
            axum::http::StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            call(app, "GET", "/probe", Some("live.secret"), None)
                .await
                .0,
            axum::http::StatusCode::OK
        );
    }

    /// A short-lived token opens the same gate as its parent secret, and the
    /// two headers are alternatives, never a precedence puzzle: presenting
    /// both is refused even when each would pass alone.
    #[tokio::test]
    async fn a_bearer_token_passes_the_gate_and_both_headers_are_refused() {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        issue_key(&conn, "live.secret", "commercial", "read:catalog", false).await;
        let st = state(db);
        let auth = store::accounts::verify_key(&DbState::from_ref(&st), "live.secret")
            .await
            .expect("parent key");
        let (token, scopes) = store::accounts::mint_token(&DbState::from_ref(&st), &auth, 300)
            .await
            .expect("mint token");
        assert_eq!(scopes, ["read:catalog"]);
        let app: Router = Router::new()
            .route("/probe", get(|| async { "ok" }))
            .layer(from_fn_with_state(st, verify_key));
        let bearer = format!("Bearer {token}");

        assert_eq!(
            call_with_headers(
                app.clone(),
                "GET",
                "/probe",
                None,
                &[("authorization", bearer.as_str())],
                None
            )
            .await
            .0,
            axum::http::StatusCode::OK
        );
        assert_eq!(
            call_with_headers(
                app,
                "GET",
                "/probe",
                Some("live.secret"),
                &[("authorization", bearer.as_str())],
                None
            )
            .await
            .0,
            axum::http::StatusCode::UNAUTHORIZED,
            "one credential per request"
        );
    }
}
