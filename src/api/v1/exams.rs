use axum::{extract::State, routing::get, Json, Router};

use crate::{
    auth::{api_key::AuthedKey, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

pub async fn list(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
) -> Result<Json<Vec<core::models::Exam>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(store::catalog::list_exams(&s).await?))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/exams", get(list))
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
        bank_schema(&conn, &["exams"]).await;
        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','Joint Admissions','[\"NG\"]','live',1,4,120,'[\"no calculator\"]')",
            (),
        )
        .await
        .expect("insert exam");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// The list is keyed, scoped, and typed: booleans and integers come back as
    /// such, and the rules array survives the round trip.
    #[tokio::test]
    async fn exams_list_is_keyed_scoped_and_typed() {
        let app = seeded_app().await;

        assert_eq!(
            call(app.clone(), "GET", "/api/v1/exams", None, None)
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );

        let (status, v) = call(app, "GET", "/api/v1/exams", Some("reader.secret"), None).await;
        assert_eq!(status, StatusCode::OK);
        let exams = v.as_array().expect("array");
        assert_eq!(exams.len(), 1);
        assert_eq!(exams[0]["code"], "JAMB");
        assert_eq!(exams[0]["countries"][0], "NG");
        assert_eq!(exams[0]["has_full_paper"], true);
        assert_eq!(exams[0]["subjects_required"], 4);
        assert_eq!(exams[0]["duration_minutes"], 120);
        assert_eq!(exams[0]["rules"][0], "no calculator");
    }
}
