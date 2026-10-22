use axum::{
    extract::{Path, Query, State},
    routing::get,
    Json, Router,
};
use serde::Deserialize;

use crate::{
    auth::{api_key::AuthedKey, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

#[derive(Deserialize, utoipa::IntoParams)]
pub struct BatchQuery {
    /// Comma-separated passage IDs to fetch in a single round-trip.
    pub ids: Option<String>,
}

#[utoipa::path(
    get,
    path = "/api/v1/passages",
    tag = "catalog",
    operation_id = "listPassages",
    summary = "Batch retrieve reading passages by IDs.",
    params(BatchQuery),
    responses(
        (status = 200, body = [core::models::Passage]),
    ),
)]
pub async fn list(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Query(f): Query<BatchQuery>,
) -> Result<Json<Vec<core::models::Passage>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let ids: Vec<String> = f
        .ids
        .as_deref()
        .unwrap_or("")
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    if ids.is_empty() {
        return Ok(Json(Vec::new()));
    }
    let map = store::catalog::get_passages(&s, &ids).await?;
    let mut out = Vec::new();
    for id in ids {
        if let Some(p) = map.get(&id) {
            out.push(p.clone());
        }
    }
    Ok(Json(out))
}

#[utoipa::path(
    get,
    path = "/api/v1/passages/{id}",
    tag = "catalog",
    operation_id = "getPassage",
    summary = "One reading passage shared by many questions.",
    params(("id" = String, Path, description = "Passage id, as a question carries it in `passage_id`.")),
    responses(
        (status = 200, body = core::models::Passage),
        (status = 404, description = "No such passage"),
    ),
)]
pub async fn one(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
) -> Result<Json<core::models::Passage>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match store::catalog::get_passage(&s, &id).await? {
        Some(p) => Ok(Json(p)),
        None => Err(AppError::NotFound),
    }
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/passages", get(list))
        .route("/v1/passages/{id}", get(one))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::testing::{api_schema, bank_schema, call, connect, issue_key, replica, state};
    use axum::http::StatusCode;

    async fn seeded_app() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["passages"]).await;
        conn.execute(
            "INSERT INTO passages VALUES ('p1','JAMB','english',2024,'comprehension','A passage','An author','Body text','[]')",
            (),
        )
        .await
        .expect("insert passage");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// The rich text decodes and an unknown id is 404, not an empty document.
    #[tokio::test]
    async fn passage_read_is_keyed_and_404s_when_absent() {
        let app = seeded_app().await;

        assert_eq!(
            call(app.clone(), "GET", "/api/v1/passages/p1", None, None)
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );

        let (status, v) = call(
            app.clone(),
            "GET",
            "/api/v1/passages/p1",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["id"], "p1");
        assert_eq!(v["year"], 2024);
        assert_eq!(v["kind"], "comprehension");
        assert_eq!(v["title"], "A passage");
        assert_eq!(v["text"]["text"], "Body text");

        assert_eq!(
            call(
                app,
                "GET",
                "/api/v1/passages/nope",
                Some("reader.secret"),
                None
            )
            .await
            .0,
            StatusCode::NOT_FOUND
        );
    }

    #[tokio::test]
    async fn batch_passage_read_is_keyed_and_returns_list() {
        let app = seeded_app().await;

        assert_eq!(
            call(app.clone(), "GET", "/api/v1/passages?ids=p1", None, None)
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );

        let (status, v) = call(
            app.clone(),
            "GET",
            "/api/v1/passages?ids=p1,missing",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let arr = v.as_array().expect("array");
        assert_eq!(arr.len(), 1);
        assert_eq!(arr[0]["id"], "p1");

        let (status, v_empty) = call(
            app,
            "GET",
            "/api/v1/passages?ids=",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v_empty.as_array().expect("array").len(), 0);
    }
}
