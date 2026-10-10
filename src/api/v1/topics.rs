//! `/api/v1/topics/{exam}/{subject}/{slug}` — one topic with its subtopics.
//!
//! The drill-down companion to the syllabus tree: where `/syllabus` returns
//! everything, this returns one node with its children and their counts.

use axum::Json;
use axum::Router;
use axum::extract::{Path, State};
use axum::routing::get;
use serde::Serialize;
use utoipa::ToSchema;

use crate::AppState;
use crate::bank::Topic;
use crate::error::ApiError;

#[derive(Serialize, ToSchema)]
pub struct TopicDetail {
    pub topic: Topic,
    pub subtopics: Vec<TopicSubtopic>,
}

#[derive(Serialize, ToSchema)]
pub struct TopicSubtopic {
    pub slug: String,
    pub name: String,
    pub order: u32,
    pub question_count: usize,
    pub objectives: Vec<String>,
}

pub fn router() -> Router<AppState> {
    Router::new().route("/v1/topics/{exam}/{subject}/{slug}", get(topic))
}

#[utoipa::path(
    get,
    path = "/api/v1/topics/{exam}/{subject}/{slug}",
    tag = "catalog",
    operation_id = "getTopic",
    description = "One topic with its subtopics, each carrying its question count and objectives.",
    params(
        ("exam" = String, Path, description = "Exam code."),
        ("subject" = String, Path, description = "Subject slug within that exam."),
        ("slug" = String, Path, description = "Topic slug."),
    ),
    responses(
        (status = 200, body = TopicDetail),
        (status = 404, description = "No such topic"),
    ),
)]
pub async fn topic(
    State(state): State<AppState>,
    Path((exam, subject, slug)): Path<(String, String, String)>,
) -> Result<Json<TopicDetail>, ApiError> {
    let (topic, subtopics) = state.bank.topic(&exam, &subject, &slug).ok_or_else(|| {
        ApiError::not_found(
            "topic_not_found",
            format!("No topic '{slug}' for {exam}/{subject}."),
        )
    })?;

    Ok(Json(TopicDetail {
        topic: topic.clone(),
        subtopics: subtopics
            .into_iter()
            .map(|st| {
                let count = state
                    .bank
                    .questions_page(
                        crate::bank::QuestionFilter {
                            subtopic: Some(&st.slug),
                            ..Default::default()
                        },
                        1,
                        1,
                    )
                    .total_records;
                TopicSubtopic {
                    slug: st.slug.clone(),
                    name: st.name.clone(),
                    order: st.order,
                    question_count: count,
                    objectives: st.objectives.clone(),
                }
            })
            .collect(),
    }))
}
