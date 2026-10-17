use axum::{
    extract::{Path, State},
    routing::get,
    Json, Router,
};

use crate::{
    auth::{api_key::AuthedKey, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

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
}
