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

pub async fn tables(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
) -> Result<Json<Vec<core::models::TableRef>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(store::catalog::table_refs(&s).await?))
}

#[derive(Deserialize)]
pub struct RowsParams {
    pub limit: Option<u64>,
}

pub async fn rows(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(table): Path<String>,
    Query(q): Query<RowsParams>,
) -> Result<Json<core::models::RowPage>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(
        store::catalog::fetch_rows(&s, &table, q.limit.unwrap_or(20)).await?,
    ))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/meta/tables", get(tables))
        .route("/v1/meta/rows/{table}", get(rows))
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
        bank_schema(&conn, &["exams", "subjects"]).await;
        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','Joint Admissions','[\"NG\"]','live',1,4,120,'[]')",
            (),
        )
        .await
        .expect("insert exam");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// The listing is deny-by-default: a credential table the schema created is
    /// absent, and the same allowlist gates the row dump, so `questions` (which
    /// carries the answer) cannot be reached by naming it.
    #[tokio::test]
    async fn meta_surface_lists_and_dumps_only_the_allowlist() {
        let app = seeded_app().await;

        assert_eq!(
            call(app.clone(), "GET", "/api/v1/meta/tables", None, None)
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );

        let (status, v) = call(
            app.clone(),
            "GET",
            "/api/v1/meta/tables",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let names: Vec<&str> = v
            .as_array()
            .expect("array")
            .iter()
            .map(|t| t["name"].as_str().expect("name"))
            .collect();
        assert_eq!(names, vec!["exams", "subjects"]);
        assert!(!names.contains(&"api_keys"), "credentials stay invisible");

        let (status, page) = call(
            app.clone(),
            "GET",
            "/api/v1/meta/rows/exams",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(page["cols"].as_array().expect("cols").len(), 8);
        let rows = page["rows"].as_array().expect("rows");
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].as_array().expect("row").len(), 8);
        assert_eq!(rows[0][0], "JAMB");

        // Off the allowlist, and absent entirely, both answer 404 so the
        // surface cannot be used to probe for names.
        for table in ["api_keys", "questions", "nope"] {
            assert_eq!(
                call(
                    app.clone(),
                    "GET",
                    &format!("/api/v1/meta/rows/{table}"),
                    Some("reader.secret"),
                    None
                )
                .await
                .0,
                StatusCode::NOT_FOUND,
                "{table} must not be dumpable"
            );
        }
    }
}
