//! `x-api-key` wire. One header, one identity for `api` + `mcp`, verified
//! once by [`verify_key`] at the router and read back by [`AuthedKey`] in
//! the handler. Verification SQL lives in `store::accounts`.

use axum::{
    body::Body,
    extract::{FromRef, FromRequestParts, State},
    http::{header::HeaderName, request::Parts, Request},
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

/// The gate: verify the presented key and stash its [`Auth`] in the request
/// extensions. Applied as a layer over every keyed router (`api/v1`, both the
/// read and write groups in `api::router`; `mcp`), so identity is a property
/// of the surface, not of remembering to write an extractor. A route on a
/// keyed router is gated whether or not it mentions `AuthedKey`; a route that
/// does mention it and was mounted outside one fails closed (401), never open.
///
/// The per-key rate limit rides here for the same reason: it cannot be
/// forgotten either. Scope does not: it differs per route, so [`Auth::require`]
/// stays one line in the handler that needs it.
pub async fn verify_key(
    State(state): State<AppState>,
    mut request: Request<Body>,
    next: Next,
) -> Result<Response, AppError> {
    let raw = request
        .headers()
        .get(HeaderName::from_static(KEY_HEADER))
        .and_then(|v| v.to_str().ok())
        .ok_or(AppError::Unauthorized)?;
    let s = DbState::from_ref(&state);
    let auth = store::accounts::verify_key(&s, raw).await?;
    if !s.limiter.check_api_key(&auth.key_id, auth.is_admin).await {
        return Err(AppError::RateLimited);
    }
    request.extensions_mut().insert(auth);
    Ok(next.run(request).await)
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
    use crate::testing::{api_schema, call, connect, issue_key, replica, state};
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
}
