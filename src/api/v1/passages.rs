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

/// Batch load passages and resolve media URLs against the configured asset host.
pub async fn load_passages_map(
    s: &DbState,
    ids: &[String],
) -> Result<std::collections::HashMap<String, core::models::Passage>, AppError> {
    if ids.is_empty() {
        return Ok(std::collections::HashMap::new());
    }
    let mut map = store::catalog::get_passages(s, ids).await?;
    for p in map.values_mut() {
        core::catalog::resolve_rich_text(&mut p.text, s.media_base_url.as_ref());
    }
    Ok(map)
}

/// Load a single passage by ID and resolve media URLs against the configured asset host.
pub async fn load_passage(
    s: &DbState,
    id: &str,
) -> Result<Option<core::models::Passage>, AppError> {
    match store::catalog::get_passage(s, id).await? {
        Some(mut p) => {
            core::catalog::resolve_rich_text(&mut p.text, s.media_base_url.as_ref());
            Ok(Some(p))
        }
        None => Ok(None),
    }
}

#[derive(Deserialize, utoipa::IntoParams)]
pub struct BatchQuery {
    /// Comma-separated passage IDs to fetch in a single round-trip.
    pub ids: Option<String>,
}

#[derive(Deserialize, utoipa::IntoParams)]
pub struct CatalogQuery {
    pub page: Option<u32>,
    pub per_page: Option<u32>,
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
        core::models::ApiErrorResponses,
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
    if !ids.is_empty() {
        if ids.len() > 100 {
            return Err(AppError::BadRequest(
                "at most 100 passage ids may be requested at once".to_string(),
            ));
        }
        let mut map = load_passages_map(&s, &ids).await?;
        let mut out = Vec::new();
        for id in ids {
            if let Some(p) = map.remove(&id) {
                out.push(p);
            }
        }
        return Ok(Json(out));
    }
    Ok(Json(Vec::new()))
}

#[utoipa::path(
    get,
    path = "/api/v1/passages/catalog/{exam}/{subject}",
    tag = "catalog",
    operation_id = "listPassageCatalog",
    summary = "A SQL-paged passage catalog for one exam and subject.",
    params(CatalogQuery),
    responses((status = 200, body = core::models::PassagePage), core::models::ApiErrorResponses),
)]
pub async fn catalog(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject)): Path<(String, String)>,
    Query(f): Query<CatalogQuery>,
) -> Result<Json<core::models::PassagePage>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let (page, per_page) = core::catalog::page_query(f.page, f.per_page);
    let (mut passages, total_records) =
        store::catalog::list_passages_page(&s, &exam, &subject, page, per_page).await?;
    for passage in &mut passages {
        core::catalog::resolve_rich_text(&mut passage.text, s.media_base_url.as_ref());
    }
    Ok(Json(core::models::PassagePage::new(
        passages,
        page,
        per_page,
        total_records,
    )))
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
        (status = 404, description = "No such passage", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn one(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
) -> Result<Json<core::models::Passage>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match load_passage(&s, &id).await? {
        Some(p) => Ok(Json(p)),
        None => Err(AppError::NotFound),
    }
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/passages", get(list))
        .route("/v1/passages/catalog/{exam}/{subject}", get(catalog))
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
            app.clone(),
            "GET",
            "/api/v1/passages?ids=",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v_empty.as_array().expect("array").len(), 0);

        let (status, v_subj) = call(
            app,
            "GET",
            "/api/v1/passages/catalog/JAMB/english",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v_subj["total_records"], 1);
        assert_eq!(v_subj["passages"][0]["id"], "p1");
    }
}
