//! Reads for the exam-neutral lesson surface.

use super::{upstream, with_conn};
use crate::{
    core::models::{ContentReference, Lesson},
    error::AppError,
    state::DbState,
};

#[derive(Clone, Debug, serde::Deserialize)]
pub struct LessonBundle {
    #[serde(default)]
    pub lessons: Vec<Lesson>,
    #[serde(default)]
    pub topic_links: Vec<TopicLessonLink>,
    #[serde(default)]
    pub example_question_links: Vec<LessonExampleQuestionLink>,
}

#[derive(Clone, Debug, serde::Deserialize)]
pub struct TopicLessonLink {
    pub exam: String,
    pub subject: String,
    pub topic_slug: String,
    #[serde(default)]
    pub subtopic_slug: Option<String>,
    pub lesson_id: String,
    #[serde(default)]
    pub order_index: i64,
}

#[derive(Clone, Debug, serde::Deserialize)]
pub struct LessonExampleQuestionLink {
    pub lesson_id: String,
    pub question_id: String,
    #[serde(default)]
    pub order_index: i64,
}

fn json_col<T: serde::de::DeserializeOwned>(
    raw: String,
    name: &'static str,
) -> Result<T, AppError> {
    serde_json::from_str(&raw).map_err(|error| AppError::Upstream(format!("{name}: {error}")))
}

fn calculated_content_hash(lesson: &Lesson) -> Result<String, AppError> {
    use sha2::Digest;
    let payload = serde_json::to_vec(&(
        &lesson.title,
        &lesson.description,
        &lesson.subject,
        &lesson.level,
        lesson.estimated_minutes,
        &lesson.objectives,
        &lesson.content,
        &lesson.checks,
        &lesson.misconceptions,
        &lesson.summary,
        &lesson.provenance,
    ))
    .map_err(|e| AppError::BadRequest(format!("lesson {} cannot be hashed: {e}", lesson.id)))?;
    Ok(format!(
        "sha256:{}",
        crate::core::hex::encode(&sha2::Sha256::digest(payload))
    ))
}

pub async fn get_lesson(s: &DbState, id: &str) -> Result<Option<Lesson>, AppError> {
    let id = id.to_string();
    with_conn(s, |conn| {
        let id = id.clone();
        async move {
            let mut rows = conn
                .query(
                    "SELECT id, status, title, description, subject, level, estimated_minutes, objectives, content, checks, misconceptions, summary, example_question_refs, provenance, content_hash FROM lessons WHERE id=?1 AND status='published' LIMIT 1",
                    [id.as_str()],
                )
                .await
                .map_err(upstream)?;
            let Some(row) = rows.next().await.map_err(upstream)? else {
                return Ok(None);
            };

            let description: String = row.get(3).map_err(upstream)?;
            let objectives: String = row.get(7).map_err(upstream)?;
            let content: String = row.get(8).map_err(upstream)?;
            let checks: String = row.get(9).map_err(upstream)?;
            let misconceptions: String = row.get(10).map_err(upstream)?;
            let summary: String = row.get(11).map_err(upstream)?;
            let example_question_refs: String = row.get(12).map_err(upstream)?;
            let provenance: String = row.get(13).map_err(upstream)?;

            Ok(Some(Lesson {
                id: row.get(0).map_err(upstream)?,
                status: row.get(1).map_err(upstream)?,
                title: row.get(2).map_err(upstream)?,
                description: json_col(description, "lessons.description")?,
                subject: row.get(4).map_err(upstream)?,
                level: row.get(5).map_err(upstream)?,
                estimated_minutes: row.get(6).map_err(upstream)?,
                objectives: json_col(objectives, "lessons.objectives")?,
                content: json_col(content, "lessons.content")?,
                checks: json_col(checks, "lessons.checks")?,
                misconceptions: json_col(misconceptions, "lessons.misconceptions")?,
                summary: json_col(summary, "lessons.summary")?,
                example_question_refs: json_col(example_question_refs, "lessons.example_question_refs")?,
                provenance: json_col(provenance, "lessons.provenance")?,
                content_hash: row.get(14).map_err(upstream)?,
            }))
        }
    })
    .await
}

pub async fn topic_lessons(
    s: &DbState,
    exam: &str,
    subject: &str,
    topic_slug: &str,
) -> Result<Vec<ContentReference>, AppError> {
    let (exam, subject, topic_slug) = (
        exam.to_string(),
        subject.to_string(),
        topic_slug.to_string(),
    );
    with_conn(s, |conn| {
        let (exam, subject, topic_slug) = (exam.clone(), subject.clone(), topic_slug.clone());
        async move {
            let mut rows = conn
                .query(
                    "SELECT lesson_refs FROM topics WHERE exam=?1 AND subject=?2 AND slug=?3",
                    [exam.as_str(), subject.as_str(), topic_slug.as_str()],
                )
                .await
                .map_err(upstream)?;
            let Some(row) = rows.next().await.map_err(upstream)? else {
                return Ok(Vec::new());
            };
            let raw: String = row.get(0).map_err(upstream)?;
            json_col(raw, "topics.lesson_refs")
        }
    })
    .await
}

pub async fn subtopic_lessons(
    s: &DbState,
    _exam: &str,
    _subject: &str,
    topic_slug: &str,
    subtopic_slug: &str,
) -> Result<Vec<ContentReference>, AppError> {
    let (topic_slug, subtopic_slug) = (topic_slug.to_string(), subtopic_slug.to_string());
    with_conn(s, |conn| {
        let (topic_slug, subtopic_slug) = (topic_slug.clone(), subtopic_slug.clone());
        async move {
            let mut rows = conn
                .query(
                    "SELECT lesson_refs FROM subtopics WHERE topic=?1 AND slug=?2",
                    [topic_slug.as_str(), subtopic_slug.as_str()],
                )
                .await
                .map_err(upstream)?;
            let Some(row) = rows.next().await.map_err(upstream)? else {
                return Ok(Vec::new());
            };
            let raw: String = row.get(0).map_err(upstream)?;
            json_col(raw, "subtopics.lesson_refs")
        }
    })
    .await
}

pub async fn import_bundle(s: &DbState, bundle: &LessonBundle) -> Result<u64, AppError> {
    let lesson_ids: std::collections::HashSet<&str> = bundle
        .lessons
        .iter()
        .map(|lesson| lesson.id.as_str())
        .collect();
    for lesson in &bundle.lessons {
        crate::core::catalog::validate_lesson(lesson)?;
        if !lesson.content_hash.is_empty()
            && lesson.content_hash != calculated_content_hash(lesson)?
        {
            return Err(AppError::BadRequest(format!(
                "lesson {} has an invalid content_hash",
                lesson.id
            )));
        }
    }
    for link in &bundle.topic_links {
        let known_lesson = lesson_ids.contains(link.lesson_id.as_str())
            || with_conn(s, |conn| {
                let id = link.lesson_id.clone();
                async move {
                    let mut rows = conn
                        .query("SELECT 1 FROM lessons WHERE id=?1", [id.as_str()])
                        .await
                        .map_err(upstream)?;
                    Ok(rows.next().await.map_err(upstream)?.is_some())
                }
            })
            .await?;
        if !known_lesson {
            return Err(AppError::BadRequest(format!(
                "topic lesson link names unknown lesson {}",
                link.lesson_id
            )));
        }
        let (exam, subject, topic, subtopic) = (
            link.exam.clone(),
            link.subject.clone(),
            link.topic_slug.clone(),
            link.subtopic_slug.clone().unwrap_or_default(),
        );
        let valid_topic = with_conn(s, |conn| {
            let exam = exam.clone(); let subject = subject.clone(); let topic = topic.clone(); let subtopic = subtopic.clone();
            async move {
            let mut rows = conn.query("SELECT 1 FROM topics t WHERE t.exam=?1 AND t.subject=?2 AND t.slug=?3 AND (?4='' OR EXISTS (SELECT 1 FROM subtopics st WHERE st.topic=t.slug AND st.slug=?4))", [exam.as_str(), subject.as_str(), topic.as_str(), subtopic.as_str()]).await.map_err(upstream)?;
            Ok(rows.next().await.map_err(upstream)?.is_some())
            }
        }).await?;
        if !valid_topic {
            return Err(AppError::BadRequest(format!(
                "topic lesson link names unknown topic {}/{}/{}",
                link.exam, link.subject, link.topic_slug
            )));
        }
        let lesson_subject = bundle
            .lessons
            .iter()
            .find(|lesson| lesson.id == link.lesson_id)
            .map(|lesson| lesson.subject.clone());
        if let Some(lesson_subject) = lesson_subject {
            if lesson_subject != link.subject {
                return Err(AppError::BadRequest(format!(
                    "lesson {} subject does not match topic subject {}",
                    link.lesson_id, link.subject
                )));
            }
        }
    }
    for link in &bundle.example_question_links {
        if !lesson_ids.contains(link.lesson_id.as_str()) {
            return Err(AppError::BadRequest(format!(
                "question lesson link names unknown lesson {}",
                link.lesson_id
            )));
        }
        let question_id = link.question_id.clone();
        let known_question = with_conn(s, |conn| {
            let question_id = question_id.clone();
            async move {
                let mut rows = conn
                    .query(
                        "SELECT 1 FROM questions WHERE id=?1",
                        [question_id.as_str()],
                    )
                    .await
                    .map_err(upstream)?;
                Ok(rows.next().await.map_err(upstream)?.is_some())
            }
        })
        .await?;
        if !known_question {
            return Err(AppError::BadRequest(format!(
                "lesson link names unknown question {}",
                link.question_id
            )));
        }
        let lesson_subject = bundle
            .lessons
            .iter()
            .find(|lesson| lesson.id == link.lesson_id)
            .map(|lesson| lesson.subject.clone());
        if let Some(lesson_subject) = lesson_subject {
            let question_id = link.question_id.clone();
            let question_subject = with_conn(s, |conn| {
                let question_id = question_id.clone();
                async move {
                    let mut rows = conn
                        .query(
                            "SELECT subject FROM questions WHERE id=?1",
                            [question_id.as_str()],
                        )
                        .await
                        .map_err(upstream)?;
                    Ok(rows
                        .next()
                        .await
                        .map_err(upstream)?
                        .and_then(|row| row.get::<String>(0).ok()))
                }
            })
            .await?;
            if question_subject.as_deref() != Some(lesson_subject.as_str()) {
                return Err(AppError::BadRequest(format!(
                    "lesson {} subject does not match question {} subject",
                    link.lesson_id, link.question_id
                )));
            }
        }
    }
    let mut statements: Vec<(&str, Vec<turso::Value>)> = Vec::new();
    for lesson in &bundle.lessons {
        let content_hash = if lesson.content_hash.is_empty() {
            calculated_content_hash(lesson)?
        } else {
            lesson.content_hash.clone()
        };
        let example_refs: Vec<ContentReference> = bundle
            .example_question_links
            .iter()
            .filter(|link| link.lesson_id == lesson.id)
            .map(|link| ContentReference {
                id: link.question_id.clone(),
                title: link.question_id.clone(),
            })
            .collect();
        let example_refs_json =
            serde_json::to_string(&example_refs).map_err(|e| AppError::Internal(e.to_string()))?;
        statements.push((
            "INSERT INTO lessons (id, status, title, description, subject, level, estimated_minutes, objectives, content, checks, misconceptions, summary, example_question_refs, provenance, content_hash) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15) ON CONFLICT(id) DO UPDATE SET status=excluded.status, title=excluded.title, description=excluded.description, subject=excluded.subject, level=excluded.level, estimated_minutes=excluded.estimated_minutes, objectives=excluded.objectives, content=excluded.content, checks=excluded.checks, misconceptions=excluded.misconceptions, summary=excluded.summary, example_question_refs=excluded.example_question_refs, provenance=excluded.provenance, content_hash=excluded.content_hash, updated_at=CURRENT_TIMESTAMP",
            vec![
                turso::Value::Text(lesson.id.clone()),
                turso::Value::Text(lesson.status.clone()),
                turso::Value::Text(lesson.title.clone()),
                turso::Value::Text(serde_json::to_string(&lesson.description).map_err(|e| AppError::Internal(e.to_string()))?),
                turso::Value::Text(lesson.subject.clone()),
                turso::Value::Text(lesson.level.clone()),
                turso::Value::Integer(lesson.estimated_minutes as i64),
                turso::Value::Text(serde_json::to_string(&lesson.objectives).map_err(|e| AppError::Internal(e.to_string()))?),
                turso::Value::Text(serde_json::to_string(&lesson.content).map_err(|e| AppError::Internal(e.to_string()))?),
                turso::Value::Text(serde_json::to_string(&lesson.checks).map_err(|e| AppError::Internal(e.to_string()))?),
                turso::Value::Text(serde_json::to_string(&lesson.misconceptions).map_err(|e| AppError::Internal(e.to_string()))?),
                turso::Value::Text(serde_json::to_string(&lesson.summary).map_err(|e| AppError::Internal(e.to_string()))?),
                turso::Value::Text(example_refs_json),
                turso::Value::Text(serde_json::to_string(&lesson.provenance).map_err(|e| AppError::Internal(e.to_string()))?),
                turso::Value::Text(content_hash),
            ],
        ));
    }
    for lesson in &bundle.lessons {
        statements.push(("UPDATE topics SET lesson_refs=COALESCE((SELECT json_group_array(json(value)) FROM json_each(COALESCE(topics.lesson_refs,'[]')) WHERE json_extract(value,'$.id')<>?1),'[]') WHERE EXISTS (SELECT 1 FROM json_each(COALESCE(topics.lesson_refs,'[]')) WHERE json_extract(value,'$.id')=?1)", vec![turso::Value::Text(lesson.id.clone())]));
        statements.push(("UPDATE subtopics SET lesson_refs=COALESCE((SELECT json_group_array(json(value)) FROM json_each(COALESCE(subtopics.lesson_refs,'[]')) WHERE json_extract(value,'$.id')<>?1),'[]') WHERE EXISTS (SELECT 1 FROM json_each(COALESCE(subtopics.lesson_refs,'[]')) WHERE json_extract(value,'$.id')=?1)", vec![turso::Value::Text(lesson.id.clone())]));
    }
    for link in &bundle.topic_links {
        let title = bundle
            .lessons
            .iter()
            .find(|lesson| lesson.id == link.lesson_id)
            .map(|lesson| lesson.title.clone())
            .unwrap_or_default();
        if let Some(subtopic) = &link.subtopic_slug {
            statements.push(("UPDATE subtopics SET lesson_refs=json_insert(COALESCE(lesson_refs,'[]'),'$[#]',json_object('id',?1,'title',?2)) WHERE topic=?3 AND slug=?4", vec![turso::Value::Text(link.lesson_id.clone()), turso::Value::Text(title), turso::Value::Text(link.topic_slug.clone()), turso::Value::Text(subtopic.clone())]));
        } else {
            statements.push(("UPDATE topics SET lesson_refs=json_insert(COALESCE(lesson_refs,'[]'),'$[#]',json_object('id',?1,'title',?2)) WHERE exam=?3 AND subject=?4 AND slug=?5", vec![turso::Value::Text(link.lesson_id.clone()), turso::Value::Text(title), turso::Value::Text(link.exam.clone()), turso::Value::Text(link.subject.clone()), turso::Value::Text(link.topic_slug.clone())]));
        }
    }
    crate::store::write::execute_write_batch(s, statements).await
}
