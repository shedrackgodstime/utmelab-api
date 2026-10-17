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
    Path((exam, subject, slug)): Path<(String, String, String)>,
) -> Result<Json<core::models::Topic>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match store::catalog::get_topic(&s, &exam, &subject, &slug).await? {
        Some(t) => Ok(Json(t)),
        None => Err(AppError::NotFound),
    }
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/topics/{exam}/{subject}/{slug}", get(one))
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
        bank_schema(&conn, &["topics"]).await;
        conn.execute(
            "INSERT INTO topics VALUES ('mechanics','physics','JAMB','Mechanics',1,0,'[\"state newton laws\"]')",
            (),
        )
        .await
        .expect("insert topic");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// The topic resolves by its full key and its objectives decode; a slug the
    /// exam does not hold is 404.
    #[tokio::test]
    async fn topic_read_is_keyed_and_404s_when_absent() {
        let app = seeded_app().await;

        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/topics/JAMB/physics/mechanics",
                None,
                None
            )
            .await
            .0,
            StatusCode::UNAUTHORIZED
        );

        let (status, v) = call(
            app.clone(),
            "GET",
            "/api/v1/topics/JAMB/physics/mechanics",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(v["slug"], "mechanics");
        assert_eq!(v["subject"], "physics");
        assert_eq!(v["order"], 1);
        assert_eq!(v["weight"], 0);
        assert_eq!(v["objectives"][0], "state newton laws");

        assert_eq!(
            call(
                app,
                "GET",
                "/api/v1/topics/JAMB/physics/nope",
                Some("reader.secret"),
                None
            )
            .await
            .0,
            StatusCode::NOT_FOUND
        );
    }
}
