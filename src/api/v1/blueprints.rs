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

#[utoipa::path(
    get,
    path = "/api/v1/blueprints/{exam}/{subject}",
    tag = "catalog",
    operation_id = "listBlueprints",
    summary = "Measured expectations for one exam subject.",
    params(
        ("exam" = String, Path, description = "Exam code, e.g. `JAMB`."),
        ("subject" = String, Path, description = "Subject slug, e.g. `physics`."),
    ),
    responses((status = 200, body = [core::models::Blueprint]), core::models::ApiErrorResponses),
)]
pub async fn list(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((exam, subject)): Path<(String, String)>,
) -> Result<Json<Vec<core::models::Blueprint>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(
        store::catalog::list_blueprints(&s, &exam, &subject).await?,
    ))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/blueprints/{exam}/{subject}", get(list))
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
        bank_schema(&conn, &["blueprints"]).await;
        conn.execute(
            "INSERT INTO blueprints VALUES ('JAMB','physics','topic','mechanics',NULL,'[\"q1\",\"q2\"]',40,12.5,10.0,15.0,5.0,4.0,6.0,'past','sample-2024','weighted','high','active',NULL)",
            (),
        )
        .await
        .expect("insert blueprint");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// Measured expectations decode with their types intact, and an unmeasured
    /// subject is an empty list, not a 404: absence is honest here.
    #[tokio::test]
    async fn blueprints_read_is_keyed_and_typed() {
        let app = seeded_app().await;

        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/blueprints/JAMB/physics",
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
            "/api/v1/blueprints/JAMB/physics",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let rows = v.as_array().expect("array");
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["exam"], "JAMB");
        assert_eq!(rows[0]["level"], "topic");
        assert_eq!(rows[0]["members"][0], "q1");
        assert_eq!(rows[0]["paper_size"], 40);
        assert_eq!(rows[0]["pct"], 12.5);
        assert_eq!(rows[0]["note"], "", "an unstored note is empty, never null");

        let (status, empty) = call(
            app,
            "GET",
            "/api/v1/blueprints/JAMB/chemistry",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(empty.as_array().expect("array").len(), 0);
    }
}
