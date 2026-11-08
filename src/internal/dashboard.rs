use axum::{
    extract::{ConnectInfo, State},
    http::HeaderMap,
    Json,
};
use serde::Deserialize;
use std::net::SocketAddr;

use crate::{
    auth::session::{self, SessionUser},
    core::models::{Applied, NewKey, PrefixBody, SignedIn},
    error::AppError,
    obs,
    state::DbState,
    store,
};

#[derive(Deserialize)]
pub struct LoginBody {
    pub username: String,
    pub password: String,
}

pub async fn login(
    State(s): State<DbState>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Json(b): Json<LoginBody>,
) -> Result<impl axum::response::IntoResponse, AppError> {
    if !s
        .limiter
        .check_login(&session::client_ip(&headers, addr))
        .await
    {
        obs::login_denied(&b.username, "rate_limited");
        return Err(AppError::RateLimited);
    }
    match store::accounts::login(&s, &b.username, &b.password).await {
        Ok((token, role)) => {
            obs::login_ok(&b.username, &role);
            let cookie = session::session_cookie_value(&token, s.cookie_secure);
            Ok((
                [(axum::http::header::SET_COOKIE, cookie)],
                Json(SignedIn { ok: true, role }),
            ))
        }
        Err(e) => {
            let reason = match &e {
                AppError::Unauthorized => "bad_credentials",
                _ => "error",
            };
            obs::login_denied(&b.username, reason);
            Err(e)
        }
    }
}

pub async fn logout(
    State(s): State<DbState>,
    headers: HeaderMap,
) -> Result<impl axum::response::IntoResponse, AppError> {
    if let Some(tok) = session::cookie_token(&headers) {
        // Best effort: logout always succeeds for the client, but the audit
        // line only lands when a live session was actually ended.
        if let Ok(Some(user)) = store::accounts::logout_session(&s, &tok).await {
            obs::logout(&user);
        }
    }
    Ok((
        [(axum::http::header::SET_COOKIE, session::expired_cookie())],
        Json(Applied { ok: true }),
    ))
}

pub async fn my_keys(
    State(s): State<DbState>,
    SessionUser(u): SessionUser,
) -> Result<Json<Vec<store::accounts::KeySummary>>, AppError> {
    Ok(Json(store::accounts::list_keys(&s, Some(&u)).await?))
}

pub async fn create_key(
    State(s): State<DbState>,
    SessionUser(u): SessionUser,
    headers: HeaderMap,
) -> Result<Json<NewKey>, AppError> {
    let idempotency_key = idempotency_key(&headers)?;
    let key = store::accounts::create_key_spec_idempotent(
        &s,
        &u,
        "commercial",
        &u,
        idempotency_key.as_deref(),
    )
    .await?;
    Ok(Json(NewKey { key }))
}

fn idempotency_key(headers: &HeaderMap) -> Result<Option<String>, AppError> {
    let Some(value) = headers.get("idempotency-key") else {
        return Ok(None);
    };
    let key = value
        .to_str()
        .map_err(|_| AppError::BadRequest("invalid idempotency key".to_string()))?
        .trim();
    if key.is_empty() || key.len() > 128 {
        return Err(AppError::BadRequest("invalid idempotency key".to_string()));
    }
    Ok(Some(key.to_string()))
}

pub async fn delete_key(
    State(s): State<DbState>,
    SessionUser(u): SessionUser,
    Json(b): Json<PrefixBody>,
) -> Result<Json<Applied>, AppError> {
    let ok = store::accounts::delete_key(&s, &u, &b.prefix).await?;
    Ok(Json(Applied { ok }))
}
