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
pub struct List {
    /// Scope to an exam.
    pub exam: Option<String>,
    /// Scope to a prescribed cycle.
    pub year: Option<u16>,
    /// Only featured texts. Default: no filter.
    pub featured: Option<bool>,
    /// Scope to a category, e.g. `literature`.
    pub category: Option<String>,
}

#[utoipa::path(
    get,
    path = "/api/v1/novels",
    tag = "catalog",
    operation_id = "listNovels",
    summary = "The prescribed-text catalog.",
    params(List),
    responses((status = 200, body = [core::models::Novel]), core::models::ApiErrorResponses),
)]
pub async fn list(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Query(f): Query<List>,
) -> Result<Json<Vec<core::models::Novel>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let mut novels = store::catalog::list_novels(
        &s,
        f.exam.as_deref(),
        f.year,
        f.featured,
        f.category.as_deref(),
    )
    .await?;
    for n in &mut novels {
        if let Some(ref mut img) = n.cover_image {
            *img = core::catalog::resolve_media_url(img, s.media_base_url.as_ref());
        }
    }
    Ok(Json(novels))
}

#[utoipa::path(
    get,
    path = "/api/v1/novels/{id}",
    tag = "catalog",
    operation_id = "getNovel",
    summary = "One novel with its chapters, characters, themes and quiz.",
    params(("id" = String, Path, description = "Novel id, e.g. `lekki`.")),
    responses(
        (status = 200, body = core::models::NovelDoc),
        (status = 404, description = "No such novel", body = core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn detail(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
) -> Result<Json<core::models::NovelDoc>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    match store::catalog::get_novel_doc(&s, &id).await? {
        Some(mut d) => {
            if let Some(ref mut img) = d.novel.cover_image {
                *img = core::catalog::resolve_media_url(img, s.media_base_url.as_ref());
            }
            for q in &mut d.questions {
                core::catalog::resolve_novel_question(q, s.media_base_url.as_ref());
            }
            Ok(Json(d))
        }
        None => Err(AppError::NotFound),
    }
}

#[derive(Deserialize, utoipa::IntoParams)]
pub struct Questions {
    /// Drill one chapter.
    pub chapter: Option<u8>,
    /// Include the answer and the working. Default: false.
    pub include_explanation: Option<bool>,
    /// 1-based page. Default: 1.
    pub page: Option<u32>,
    /// Rows per page, clamped. Default: 50, cap: 200.
    pub per_page: Option<u32>,
}

#[utoipa::path(
    get,
    path = "/api/v1/novels/{id}/questions",
    tag = "catalog",
    operation_id = "listNovelQuestions",
    summary = "A novel's quiz, one page. The answer is withheld unless asked for.",
    params(
        ("id" = String, Path, description = "Novel id, e.g. `lekki`."),
        Questions,
    ),
    responses(
        (status = 200, body = core::models::Page<core::models::RenderedNovelQuestion>),
        (status = 404, description = "No such novel", body = core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn questions(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(id): Path<String>,
    Query(f): Query<Questions>,
) -> Result<Json<core::models::NovelQuestionPage>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let with_explanation = f.include_explanation.unwrap_or(false);
    let (page, per_page) = core::catalog::page_query(f.page, f.per_page);
    let all = store::catalog::list_novel_questions(&s, &id, f.chapter).await?;
    if all.is_empty() && store::catalog::get_novel_doc(&s, &id).await?.is_none() {
        return Err(AppError::NotFound);
    }
    let total_records = all.len();
    let start = ((page - 1) * per_page) as usize;
    let rendered = all
        .into_iter()
        .skip(start)
        .take(per_page as usize)
        .map(|q| {
            core::catalog::render_novel_question(
                &id,
                &q,
                with_explanation,
                s.media_base_url.as_ref(),
            )
        })
        .collect();
    Ok(Json(core::models::Page::new(
        rendered,
        page,
        per_page,
        total_records,
        with_explanation,
    )))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/novels", get(list))
        .route("/v1/novels/{id}", get(detail))
        .route("/v1/novels/{id}/questions", get(questions))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use crate::testing::{api_schema, bank_schema, call, connect, issue_key, replica, state};
    use axum::http::StatusCode;

    const BANK_TABLES: &[&str] = &[
        "novels",
        "novel_chapters",
        "novel_characters",
        "novel_themes",
        "novel_questions",
        "verifications",
    ];

    async fn seeded_app() -> axum::Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(&conn, BANK_TABLES).await;
        conn.execute(
            "INSERT INTO novels VALUES ('lekki','Lekki Headmaster','Author',2010,'JAMB','[2024,2025]','literature',1,'A synopsis','Lagos','1970s',NULL)",
            (),
        )
        .await
        .expect("insert novel");
        conn.execute(
            "INSERT INTO novel_questions VALUES ('nq1','lekki',1,'Who is the headmaster?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"Lekki\",\"inline\":[]}}]','a',NULL,'h2')",
            (),
        )
        .await
        .expect("insert novel question");
        issue_key(&conn, "reader.secret", "commercial", "read:catalog", false).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// All three reads: the list decodes JSON columns, the detail assembles the
    /// document, and the quiz page withholds the answer by default.
    #[tokio::test]
    async fn novel_reads_are_keyed_listed_and_paged() {
        let app = seeded_app().await;

        assert_eq!(
            call(app.clone(), "GET", "/api/v1/novels", None, None)
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );

        let (status, list) = call(
            app.clone(),
            "GET",
            "/api/v1/novels",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let novels = list.as_array().expect("array");
        assert_eq!(novels.len(), 1);
        assert_eq!(novels[0]["id"], "lekki");
        assert_eq!(novels[0]["featured"], true);
        assert_eq!(
            novels[0]["year_prescribed"],
            serde_json::json!([2024, 2025])
        );

        let (status, doc) = call(
            app.clone(),
            "GET",
            "/api/v1/novels/lekki",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(doc["id"], "lekki");
        assert_eq!(doc["chapters"].as_array().expect("chapters").len(), 0);
        assert_eq!(doc["questions"].as_array().expect("questions").len(), 1);

        let (status, page) = call(
            app.clone(),
            "GET",
            "/api/v1/novels/lekki/questions",
            Some("reader.secret"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(page["total_records"], 1);
        assert_eq!(page["questions"][0]["id"], "nq1");
        assert!(
            page["questions"][0].get("answer").is_none(),
            "answer withheld"
        );

        // Unknown ids 404 on both detail and quiz.
        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/novels/nope",
                Some("reader.secret"),
                None
            )
            .await
            .0,
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            call(
                app,
                "GET",
                "/api/v1/novels/nope/questions",
                Some("reader.secret"),
                None
            )
            .await
            .0,
            StatusCode::NOT_FOUND
        );
    }
}
