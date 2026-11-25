//! Reads for the exam-neutral lesson surface.

use std::collections::{HashMap, HashSet};

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

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct LinkParent {
    exam: String,
    subject: String,
    topic_slug: String,
    subtopic_slug: String,
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

pub(crate) async fn published_lesson_titles(
    s: &DbState,
) -> Result<HashMap<String, String>, AppError> {
    with_conn(s, |conn| async move {
        let mut rows = conn
            .query("SELECT id, title FROM lessons WHERE status='published'", ())
            .await
            .map_err(upstream)?;
        let mut titles = HashMap::new();
        while let Some(row) = rows.next().await.map_err(upstream)? {
            let id: String = row.get(0).map_err(upstream)?;
            let title: String = row.get(1).map_err(upstream)?;
            titles.insert(id, title);
        }
        Ok(titles)
    })
    .await
}

fn numbered_refs(refs: Vec<ContentReference>) -> Vec<ContentReference> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for mut reference in refs {
        if !seen.insert(reference.id.clone()) {
            continue;
        }
        reference.order = out.len() as u32 + 1;
        out.push(reference);
    }
    out
}

fn parse_refs(raw: &str, name: &'static str) -> Result<Vec<ContentReference>, AppError> {
    json_col(raw.to_string(), name)
}

pub(crate) fn visible_refs(
    raw: &str,
    name: &'static str,
    titles: &HashMap<String, String>,
) -> Result<Vec<ContentReference>, AppError> {
    let refs = parse_refs(raw, name)?
        .into_iter()
        .filter_map(|mut reference| {
            titles.get(&reference.id).map(|title| {
                reference.title = title.clone();
                reference
            })
        })
        .collect();
    Ok(numbered_refs(refs))
}

/// Filter stored refs to published lessons and number them from the JSON array.
pub async fn visible_lesson_refs(
    s: &DbState,
    raw: &str,
    name: &'static str,
) -> Result<Vec<ContentReference>, AppError> {
    let titles = published_lesson_titles(s).await?;
    visible_refs(raw, name, &titles)
}

/// One subject's topic and subtopic refs, read from the same JSON rows the
/// topic detail surface reads. The array position is the curriculum order.
#[derive(Clone, Debug, Default)]
pub struct SyllabusLessonRefs {
    topics: HashMap<String, Vec<ContentReference>>,
    subtopics: HashMap<(String, String), Vec<ContentReference>>,
}

impl SyllabusLessonRefs {
    pub fn topic(&self, slug: &str) -> Vec<ContentReference> {
        self.topics.get(slug).cloned().unwrap_or_default()
    }

    pub fn subtopic(&self, topic: &str, subtopic: &str) -> Vec<ContentReference> {
        self.subtopics
            .get(&(topic.to_string(), subtopic.to_string()))
            .cloned()
            .unwrap_or_default()
    }
}

pub async fn syllabus_lesson_refs(
    s: &DbState,
    exam: &str,
    subject: &str,
) -> Result<SyllabusLessonRefs, AppError> {
    let (exam, subject) = (exam.to_string(), subject.to_string());
    let titles = published_lesson_titles(s).await?;
    with_conn(s, |conn| {
        let (exam, subject, titles) = (exam.clone(), subject.clone(), titles.clone());
        async move {
            let mut out = SyllabusLessonRefs::default();
            let mut rows = conn
                .query(
                    "SELECT slug, COALESCE(lesson_refs,'[]') FROM topics WHERE exam=?1 AND subject=?2",
                    [exam.as_str(), subject.as_str()],
                )
                .await
                .map_err(upstream)?;
            while let Some(row) = rows.next().await.map_err(upstream)? {
                let slug: String = row.get(0).map_err(upstream)?;
                let raw: String = row.get(1).map_err(upstream)?;
                out.topics
                    .insert(slug, visible_refs(&raw, "topics.lesson_refs", &titles)?);
            }

            let mut ambiguous = conn
                .query(
                    "SELECT st.topic FROM subtopics st JOIN topics t ON t.slug=st.topic WHERE t.exam=?1 AND t.subject=?2 GROUP BY st.topic HAVING (SELECT COUNT(DISTINCT t2.exam || '/' || t2.subject) FROM topics t2 WHERE t2.slug=st.topic) > 1 LIMIT 1",
                    [exam.as_str(), subject.as_str()],
                )
                .await
                .map_err(upstream)?;
            if let Some(row) = ambiguous.next().await.map_err(upstream)? {
                return Err(ambiguous_topic_error(
                    &row.get::<String>(0).map_err(upstream)?,
                ));
            }

            let mut rows = conn
                .query(
                    "SELECT st.topic, st.slug, COALESCE(st.lesson_refs,'[]') FROM subtopics st JOIN topics t ON t.slug=st.topic WHERE t.exam=?1 AND t.subject=?2 ORDER BY st.topic, st.slug",
                    [exam.as_str(), subject.as_str()],
                )
                .await
                .map_err(upstream)?;
            while let Some(row) = rows.next().await.map_err(upstream)? {
                let topic: String = row.get(0).map_err(upstream)?;
                let subtopic: String = row.get(1).map_err(upstream)?;
                let raw: String = row.get(2).map_err(upstream)?;
                out.subtopics.insert(
                    (topic, subtopic),
                    visible_refs(&raw, "subtopics.lesson_refs", &titles)?,
                );
            }
            Ok(out)
        }
    })
    .await
}

async fn has_table(s: &DbState, name: &str) -> Result<bool, AppError> {
    let name = name.to_string();
    with_conn(s, |conn| {
        let name = name.clone();
        async move {
            let mut rows = conn
                .query(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1",
                    [name.as_str()],
                )
                .await
                .map_err(upstream)?;
            Ok(rows.next().await.map_err(upstream)?.is_some())
        }
    })
    .await
}

/// Place links at their authored position. Existing refs keep their relative
/// order, and links already present keep their stored position.
fn insert_link_refs<'a>(
    mut refs: Vec<ContentReference>,
    links: impl Iterator<Item = &'a TopicLessonLink>,
    titles: &HashMap<String, String>,
) -> Vec<ContentReference> {
    let mut links: Vec<_> = links.collect();
    links.sort_by_key(|link| link.order_index);
    let mut seen: HashSet<String> = refs.iter().map(|reference| reference.id.clone()).collect();
    for link in links {
        if !seen.insert(link.lesson_id.clone()) {
            continue;
        }
        let at = (link.order_index as usize)
            .saturating_sub(1)
            .min(refs.len());
        refs.insert(
            at,
            ContentReference {
                id: link.lesson_id.clone(),
                title: titles.get(&link.lesson_id).cloned().unwrap_or_default(),
                order: 0,
            },
        );
    }
    numbered_refs(refs)
}

/// A subtopic row is keyed by topic slug only. If two exams own one topic slug,
/// the shared row cannot carry exam-specific refs, so readers and writers fail
/// closed instead of serving one exam's refs to another.
fn ambiguous_topic_error(slug: &str) -> AppError {
    AppError::Internal(format!(
        "topic slug {slug} has multiple syllabus owners; subtopic lesson refs cannot be scoped"
    ))
}

async fn ambiguous_topic_slugs(s: &DbState) -> Result<Vec<String>, AppError> {
    with_conn(s, |conn| async move {
        let mut rows = conn
            .query(
                "SELECT t.slug FROM topics t JOIN subtopics st ON st.topic=t.slug GROUP BY t.slug HAVING COUNT(DISTINCT t.exam || '/' || t.subject) > 1",
                (),
            )
            .await
            .map_err(upstream)?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().await.map_err(upstream)? {
            out.push(row.get::<String>(0).map_err(upstream)?);
        }
        Ok(out)
    })
    .await
}

async fn assert_topic_owner_unambiguous(s: &DbState, slug: &str) -> Result<(), AppError> {
    let slug = slug.to_string();
    if ambiguous_topic_slugs(s)
        .await?
        .iter()
        .any(|candidate| candidate == &slug)
    {
        return Err(ambiguous_topic_error(&slug));
    }
    Ok(())
}

/// Rewrite stored refs with array positions in the `order` field. This repairs
/// refs copied before the canonical ordering field was written.
pub(crate) async fn normalize_lesson_ref_orders_local(s: &DbState) -> Result<(), AppError> {
    for (table, where_sql) in [
        ("topics", "exam IS NOT NULL"),
        ("subtopics", "topic IS NOT NULL"),
    ] {
        if !has_table(s, table).await? {
            continue;
        }
        let rows: Vec<(i64, String)> = with_conn(s, |conn| {
            let sql =
                format!("SELECT rowid, COALESCE(lesson_refs,'[]') FROM {table} WHERE {where_sql}");
            async move {
                let mut rows = conn.query(&sql, ()).await.map_err(upstream)?;
                let mut out = Vec::new();
                while let Some(row) = rows.next().await.map_err(upstream)? {
                    out.push((row.get(0).map_err(upstream)?, row.get(1).map_err(upstream)?));
                }
                Ok(out)
            }
        })
        .await?;
        for (rowid, raw) in rows {
            let refs = numbered_refs(parse_refs(&raw, "lesson_refs")?);
            let json =
                serde_json::to_string(&refs).map_err(|e| AppError::Internal(e.to_string()))?;
            if json != raw {
                let sql = format!("UPDATE {table} SET lesson_refs=?1 WHERE rowid=?2");
                super::write::execute_write_local(
                    s,
                    &sql,
                    vec![turso::Value::Text(json), turso::Value::Integer(rowid)],
                )
                .await?;
            }
        }
    }
    Ok(())
}

/// Fold the retired relationship table into the JSON refs before it is
/// dropped. Existing JSON wins when both sources name the same lesson. Shared
/// subtopic rows with more than one syllabus owner are left untouched.
pub(crate) async fn backfill_lesson_refs_local(s: &DbState) -> Result<(), AppError> {
    let titles = published_lesson_titles(s).await?;
    let has_topics = has_table(s, "topics").await?;
    let has_subtopics = has_table(s, "subtopics").await?;
    let has_links = has_table(s, "topic_lessons").await?;
    if !has_topics && !has_subtopics {
        return Ok(());
    }
    let ambiguous = if has_topics && has_subtopics {
        ambiguous_topic_slugs(s).await?
    } else {
        Vec::new()
    };

    let links: Vec<TopicLessonLink> = if has_links {
        with_conn(s, |conn| async move {
            let mut rows = conn
                .query(
                    "SELECT exam, subject, topic_slug, COALESCE(subtopic_slug,''), lesson_id, order_index FROM topic_lessons ORDER BY exam, subject, topic_slug, subtopic_slug, order_index, lesson_id",
                    (),
                )
                .await
                .map_err(upstream)?;
            let mut out = Vec::new();
            while let Some(row) = rows.next().await.map_err(upstream)? {
                let subtopic: String = row.get(3).map_err(upstream)?;
                out.push(TopicLessonLink {
                    exam: row.get(0).map_err(upstream)?,
                    subject: row.get(1).map_err(upstream)?,
                    topic_slug: row.get(2).map_err(upstream)?,
                    subtopic_slug: if subtopic.is_empty() {
                        None
                    } else {
                        Some(subtopic)
                    },
                    lesson_id: row.get(4).map_err(upstream)?,
                    order_index: row.get(5).map_err(upstream)?,
                });
            }
            Ok(out)
        })
        .await?
    } else {
        Vec::new()
    };

    let mut statements: Vec<(&str, Vec<turso::Value>)> = Vec::new();
    if has_topics {
        let topics: Vec<(String, String, String, String)> = with_conn(s, |conn| async move {
            let mut rows = conn
                .query(
                    "SELECT slug, exam, subject, COALESCE(lesson_refs,'[]') FROM topics",
                    (),
                )
                .await
                .map_err(upstream)?;
            let mut out = Vec::new();
            while let Some(row) = rows.next().await.map_err(upstream)? {
                out.push((
                    row.get(0).map_err(upstream)?,
                    row.get(1).map_err(upstream)?,
                    row.get(2).map_err(upstream)?,
                    row.get(3).map_err(upstream)?,
                ));
            }
            Ok(out)
        })
        .await?;
        for (slug, exam, subject, raw) in topics {
            let refs = parse_refs(&raw, "topics.lesson_refs")?;
            let refs = insert_link_refs(
                refs,
                links.iter().filter(|link| {
                    link.exam == exam
                        && link.subject == subject
                        && link.topic_slug == slug
                        && link.subtopic_slug.as_deref().unwrap_or_default().is_empty()
                }),
                &titles,
            );
            let json =
                serde_json::to_string(&refs).map_err(|e| AppError::Internal(e.to_string()))?;
            if json == raw {
                continue;
            }
            statements.push((
                "UPDATE topics SET lesson_refs=?1 WHERE exam=?2 AND subject=?3 AND slug=?4",
                vec![
                    turso::Value::Text(json),
                    turso::Value::Text(exam),
                    turso::Value::Text(subject),
                    turso::Value::Text(slug),
                ],
            ));
        }
    }

    if has_subtopics && has_topics {
        let subtopics: Vec<(String, String, String, String, String)> =
            with_conn(s, |conn| async move {
                let mut rows = conn
                    .query(
                        "SELECT st.slug, t.slug, t.exam, t.subject, COALESCE(st.lesson_refs,'[]') FROM subtopics st JOIN topics t ON t.slug=st.topic",
                        (),
                    )
                    .await
                    .map_err(upstream)?;
                let mut out = Vec::new();
                while let Some(row) = rows.next().await.map_err(upstream)? {
                    out.push((
                        row.get(0).map_err(upstream)?,
                        row.get(1).map_err(upstream)?,
                        row.get(2).map_err(upstream)?,
                        row.get(3).map_err(upstream)?,
                        row.get(4).map_err(upstream)?,
                    ));
                }
                Ok(out)
            })
            .await?;
        for (slug, topic, exam, subject, raw) in subtopics {
            if ambiguous.iter().any(|candidate| candidate == &topic) {
                continue;
            }
            let refs = parse_refs(&raw, "subtopics.lesson_refs")?;
            let refs = insert_link_refs(
                refs,
                links.iter().filter(|link| {
                    link.exam == exam
                        && link.subject == subject
                        && link.topic_slug == topic
                        && link.subtopic_slug.as_deref() == Some(slug.as_str())
                }),
                &titles,
            );
            let json =
                serde_json::to_string(&refs).map_err(|e| AppError::Internal(e.to_string()))?;
            if json == raw {
                continue;
            }
            statements.push((
                "UPDATE subtopics SET lesson_refs=?1 WHERE topic=?2 AND slug=?3 AND EXISTS (SELECT 1 FROM topics t WHERE t.slug=subtopics.topic AND t.exam=?4 AND t.subject=?5)",
                vec![
                    turso::Value::Text(json),
                    turso::Value::Text(topic),
                    turso::Value::Text(slug),
                    turso::Value::Text(exam),
                    turso::Value::Text(subject),
                ],
            ));
        }
    }
    for (sql, params) in statements {
        super::write::execute_write_local(s, sql, params).await?;
    }
    Ok(())
}

async fn raw_parent_refs(s: &DbState, parent: &LinkParent) -> Result<String, AppError> {
    if parent.subtopic_slug.is_empty() {
        with_conn(s, |conn| {
            let parent = parent.clone();
            async move {
                let mut rows = conn
                    .query(
                        "SELECT COALESCE(lesson_refs,'[]') FROM topics WHERE exam=?1 AND subject=?2 AND slug=?3",
                        [
                            parent.exam.as_str(),
                            parent.subject.as_str(),
                            parent.topic_slug.as_str(),
                        ],
                    )
                    .await
                    .map_err(upstream)?;
                Ok(rows
                    .next()
                    .await
                    .map_err(upstream)?
                    .and_then(|row| row.get(0).ok())
                    .unwrap_or_else(|| "[]".to_string()))
            }
        })
        .await
    } else {
        assert_topic_owner_unambiguous(s, &parent.topic_slug).await?;
        with_conn(s, |conn| {
            let parent = parent.clone();
            async move {
                let mut rows = conn
                    .query(
                        "SELECT COALESCE(st.lesson_refs,'[]') FROM subtopics st JOIN topics t ON t.slug=st.topic WHERE st.topic=?1 AND st.slug=?2 AND t.exam=?3 AND t.subject=?4",
                        [
                            parent.topic_slug.as_str(),
                            parent.subtopic_slug.as_str(),
                            parent.exam.as_str(),
                            parent.subject.as_str(),
                        ],
                    )
                    .await
                    .map_err(upstream)?;
                Ok(rows
                    .next()
                    .await
                    .map_err(upstream)?
                    .and_then(|row| row.get(0).ok())
                    .unwrap_or_else(|| "[]".to_string()))
            }
        })
        .await
    }
}

pub async fn import_bundle(s: &DbState, bundle: &LessonBundle) -> Result<u64, AppError> {
    let mut topic_link_orders = std::collections::HashSet::new();
    let mut topic_link_keys = std::collections::HashSet::new();
    for link in &bundle.topic_links {
        if link.order_index < 1 {
            return Err(AppError::BadRequest(format!(
                "lesson link {} has an order_index below 1",
                link.lesson_id
            )));
        }
        let subtopic = link.subtopic_slug.as_deref().unwrap_or_default();
        let parent = (
            link.exam.as_str(),
            link.subject.as_str(),
            link.topic_slug.as_str(),
            subtopic,
        );
        if !topic_link_keys.insert((parent, link.lesson_id.as_str())) {
            return Err(AppError::BadRequest(format!(
                "duplicate lesson link {} for {}/{}/{}{}",
                link.lesson_id,
                link.exam,
                link.subject,
                link.topic_slug,
                if subtopic.is_empty() {
                    String::new()
                } else {
                    format!("/{subtopic}")
                }
            )));
        }
        if !topic_link_orders.insert((parent, link.order_index)) {
            return Err(AppError::BadRequest(format!(
                "duplicate lesson order_index {} for {}/{}/{}{}",
                link.order_index,
                link.exam,
                link.subject,
                link.topic_slug,
                if subtopic.is_empty() {
                    String::new()
                } else {
                    format!("/{subtopic}")
                }
            )));
        }
    }
    let mut example_link_orders = std::collections::HashSet::new();
    for link in &bundle.example_question_links {
        if link.order_index < 0 {
            return Err(AppError::BadRequest(format!(
                "example question link {} has a negative order_index",
                link.question_id
            )));
        }
        if !example_link_orders.insert((link.lesson_id.as_str(), link.order_index)) {
            return Err(AppError::BadRequest(format!(
                "duplicate example question order_index {} for lesson {}",
                link.order_index, link.lesson_id
            )));
        }
    }
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
        let stored_subject = if lesson_ids.contains(link.lesson_id.as_str()) {
            None
        } else {
            with_conn(s, |conn| {
                let id = link.lesson_id.clone();
                async move {
                    let mut rows = conn
                        .query("SELECT subject FROM lessons WHERE id=?1", [id.as_str()])
                        .await
                        .map_err(upstream)?;
                    let subject: Option<String> = rows
                        .next()
                        .await
                        .map_err(upstream)?
                        .and_then(|row| row.get(0).ok());
                    Ok(subject)
                }
            })
            .await?
        };
        if stored_subject.is_none() && !lesson_ids.contains(link.lesson_id.as_str()) {
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
        if !subtopic.is_empty() {
            assert_topic_owner_unambiguous(s, &topic).await?;
        }
        let lesson_subject = bundle
            .lessons
            .iter()
            .find(|lesson| lesson.id == link.lesson_id)
            .map(|lesson| lesson.subject.clone())
            .or(stored_subject);
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
    let bundle_titles: HashMap<&str, String> = bundle
        .lessons
        .iter()
        .map(|lesson| (lesson.id.as_str(), lesson.title.clone()))
        .collect();
    let existing_titles = published_lesson_titles(s).await?;
    let mut link_groups: HashMap<LinkParent, Vec<&TopicLessonLink>> = HashMap::new();
    for link in &bundle.topic_links {
        let parent = LinkParent {
            exam: link.exam.clone(),
            subject: link.subject.clone(),
            topic_slug: link.topic_slug.clone(),
            subtopic_slug: link.subtopic_slug.clone().unwrap_or_default(),
        };
        link_groups.entry(parent).or_default().push(link);
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
                order: link.order_index as u32,
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
    for (parent, mut links) in link_groups {
        links.sort_by_key(|link| link.order_index);
        let raw = raw_parent_refs(s, &parent).await?;
        let link_ids: HashSet<&str> = links.iter().map(|link| link.lesson_id.as_str()).collect();
        let mut refs: Vec<ContentReference> = parse_refs(&raw, "lesson_refs")?
            .into_iter()
            .filter(|reference| !link_ids.contains(reference.id.as_str()))
            .collect();
        for link in links {
            let title = bundle_titles
                .get(link.lesson_id.as_str())
                .cloned()
                .or_else(|| existing_titles.get(&link.lesson_id).cloned())
                .unwrap_or_default();
            let at = (link.order_index as usize)
                .saturating_sub(1)
                .min(refs.len());
            refs.insert(
                at,
                ContentReference {
                    id: link.lesson_id.clone(),
                    title,
                    order: 0,
                },
            );
        }
        let json = serde_json::to_string(&numbered_refs(refs))
            .map_err(|e| AppError::Internal(e.to_string()))?;
        if parent.subtopic_slug.is_empty() {
            statements.push((
                "UPDATE topics SET lesson_refs=?1 WHERE exam=?2 AND subject=?3 AND slug=?4",
                vec![
                    turso::Value::Text(json),
                    turso::Value::Text(parent.exam),
                    turso::Value::Text(parent.subject),
                    turso::Value::Text(parent.topic_slug),
                ],
            ));
        } else {
            statements.push((
                "UPDATE subtopics SET lesson_refs=?1 WHERE topic=?2 AND slug=?3 AND EXISTS (SELECT 1 FROM topics t WHERE t.slug=subtopics.topic AND t.exam=?4 AND t.subject=?5)",
                vec![
                    turso::Value::Text(json),
                    turso::Value::Text(parent.topic_slug),
                    turso::Value::Text(parent.subtopic_slug),
                    turso::Value::Text(parent.exam),
                    turso::Value::Text(parent.subject),
                ],
            ));
        }
    }
    crate::store::write::execute_write_batch(s, statements).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        core::models::{
            ContentBlock, OpeningAnchor, RichText, StudyCheck, StudyCheckAnswer, StudyCheckKind,
            StudyCheckOption,
        },
        testing::{api_schema, bank_schema, conn_of, db_state, replica},
    };

    fn valid_lesson(id: &str, subject: &str, title: &str) -> Lesson {
        let text = || RichText {
            text: "Text".to_string(),
            inline: Vec::new(),
        };
        Lesson {
            id: id.to_string(),
            status: "published".to_string(),
            title: title.to_string(),
            description: RichText::default(),
            subject: subject.to_string(),
            level: "secondary".to_string(),
            estimated_minutes: 5,
            objectives: Vec::new(),
            content: vec![
                ContentBlock::Opening {
                    id: "opening".to_string(),
                    anchor: OpeningAnchor::Scenario,
                    heading: "Start".to_string(),
                    text: text(),
                },
                ContentBlock::Example {
                    id: "example".to_string(),
                    title: None,
                    prompt: text(),
                    steps: Vec::new(),
                    answer: None,
                },
            ],
            checks: vec![StudyCheck {
                id: "check".to_string(),
                order: 1,
                position_after_block_id: None,
                objective_id: None,
                kind: StudyCheckKind::MultipleChoice,
                prompt: text(),
                options: vec![StudyCheckOption {
                    id: "option".to_string(),
                    content: text(),
                }],
                answer: StudyCheckAnswer {
                    option_id: "option".to_string(),
                },
                feedback: text(),
                hint: None,
                provenance: Default::default(),
            }],
            misconceptions: Vec::new(),
            summary: vec![text()],
            example_question_refs: Vec::new(),
            provenance: Default::default(),
            content_hash: String::new(),
        }
    }

    #[tokio::test]
    async fn import_bundle_feeds_both_exam_syllabuses_from_json_refs() {
        let s = db_state(replica().await);
        let conn = conn_of(&s).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &["exams", "subjects", "topics", "subtopics", "questions"],
        )
        .await;

        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','JAMB','[\"NG\"]','active',1,NULL,NULL,'[]')",
            (),
        )
        .await
        .expect("jamb exam");
        conn.execute(
            "INSERT INTO exams VALUES ('WAEC','WAEC','[\"NG\"]','active',1,NULL,NULL,'[]')",
            (),
        )
        .await
        .expect("waec exam");
        for exam in ["JAMB", "WAEC"] {
            conn.execute(
                "INSERT INTO subjects VALUES ('english-language',?1,'English Language',0,0,50,'[]',NULL,NULL)",
                [exam],
            )
            .await
            .expect("subject");
            let slug = format!("{}-comprehension", exam.to_ascii_lowercase());
            conn.execute(
                "INSERT INTO topics VALUES (?1,'english-language',?2,'Comprehension',1,0,'[]','[]','[]')",
                [slug.as_str(), exam],
            )
            .await
            .expect("topic");
        }
        conn.execute(
            "INSERT INTO subtopics VALUES ('comprehension','jamb-comprehension','Comprehension',1,'[]','[]')",
            (),
        )
        .await
        .expect("subtopic");
        for (id, title) in [
            ("lesson:english:first", "First lesson"),
            ("lesson:english:second", "Second lesson"),
        ] {
            conn.execute(
                "INSERT INTO lessons (id,status,title,description,subject,level,estimated_minutes,objectives,content,checks,misconceptions,summary,example_question_refs,provenance,content_hash) VALUES (?1,'published',?2,'{}','english-language','secondary',5,'[]','[]','[]','[]','[]','[]','{}','hash')",
                [id, title],
            )
            .await
            .expect("lesson");
        }

        let link = |exam: &str, topic: &str, subtopic: Option<&str>, id: &str, order: i64| {
            TopicLessonLink {
                exam: exam.to_string(),
                subject: "english-language".to_string(),
                topic_slug: topic.to_string(),
                subtopic_slug: subtopic.map(str::to_string),
                lesson_id: id.to_string(),
                order_index: order,
            }
        };
        let bundle = LessonBundle {
            lessons: Vec::new(),
            topic_links: vec![
                link(
                    "JAMB",
                    "jamb-comprehension",
                    None,
                    "lesson:english:second",
                    2,
                ),
                link(
                    "JAMB",
                    "jamb-comprehension",
                    None,
                    "lesson:english:first",
                    1,
                ),
                link(
                    "WAEC",
                    "waec-comprehension",
                    None,
                    "lesson:english:first",
                    1,
                ),
                link(
                    "JAMB",
                    "jamb-comprehension",
                    Some("comprehension"),
                    "lesson:english:first",
                    1,
                ),
            ],
            example_question_links: Vec::new(),
        };
        import_bundle(&s, &bundle).await.expect("import");
        import_bundle(&s, &bundle)
            .await
            .expect("reimport is idempotent");

        let refs = syllabus_lesson_refs(&s, "JAMB", "english-language")
            .await
            .expect("jamb refs");
        assert_eq!(
            refs.topic("jamb-comprehension"),
            vec![
                ContentReference {
                    id: "lesson:english:first".to_string(),
                    title: "First lesson".to_string(),
                    order: 1,
                },
                ContentReference {
                    id: "lesson:english:second".to_string(),
                    title: "Second lesson".to_string(),
                    order: 2,
                },
            ]
        );
        assert_eq!(
            refs.subtopic("jamb-comprehension", "comprehension")[0].id,
            "lesson:english:first"
        );

        let waec = syllabus_lesson_refs(&s, "WAEC", "english-language")
            .await
            .expect("waec refs");
        assert_eq!(waec.topic("waec-comprehension").len(), 1);
        assert_eq!(
            waec.topic("waec-comprehension")[0].id,
            "lesson:english:first"
        );

        let jamb_syllabus =
            crate::api::v1::subjects::build_syllabus(&s, "JAMB", "english-language", None)
                .await
                .expect("jamb syllabus");
        assert_eq!(jamb_syllabus.topics[0].lesson_refs.len(), 2);
        let waec_syllabus =
            crate::api::v1::subjects::build_syllabus(&s, "WAEC", "english-language", None)
                .await
                .expect("waec syllabus");
        assert_eq!(
            waec_syllabus.topics[0].lesson_refs[0].id,
            "lesson:english:first"
        );

        let topic =
            crate::store::catalog::get_topic(&s, "JAMB", "english-language", "jamb-comprehension")
                .await
                .expect("topic read")
                .expect("topic present");
        assert_eq!(topic.lesson_refs, refs.topic("jamb-comprehension"));
    }

    #[tokio::test]
    async fn visible_refs_hide_drafts_and_number_from_array_position() {
        let s = db_state(replica().await);
        let conn = conn_of(&s).await;
        api_schema(&conn).await;
        conn.execute(
            "INSERT INTO lessons (id,status,title,description,subject,level,estimated_minutes,objectives,content,checks,misconceptions,summary,example_question_refs,provenance,content_hash) VALUES ('lesson:live','published','Live','{}','physics','secondary',5,'[]','[]','[]','[]','[]','[]','{}','hash')",
            (),
        )
        .await
        .expect("published lesson");
        conn.execute(
            "INSERT INTO lessons (id,status,title,description,subject,level,estimated_minutes,objectives,content,checks,misconceptions,summary,example_question_refs,provenance,content_hash) VALUES ('lesson:draft','draft','Draft','{}','physics','secondary',5,'[]','[]','[]','[]','[]','[]','{}','hash')",
            (),
        )
        .await
        .expect("draft lesson");

        let refs = visible_lesson_refs(
            &s,
            r#"[{"id":"lesson:draft","title":"Draft","order":1},{"id":"lesson:live","title":"Old title","order":9}]"#,
            "test.lesson_refs",
        )
        .await
        .expect("visible refs");
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].id, "lesson:live");
        assert_eq!(refs[0].title, "Live");
        assert_eq!(refs[0].order, 1);
    }

    #[tokio::test]
    async fn import_bundle_preserves_refs_on_parents_outside_partial_bundle() {
        let s = db_state(replica().await);
        let conn = conn_of(&s).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &["exams", "subjects", "topics", "subtopics", "questions"],
        )
        .await;

        for exam in ["JAMB", "WAEC"] {
            conn.execute(
                "INSERT INTO exams VALUES (?1,?1,'[\"NG\"]','active',1,NULL,NULL,'[]')",
                [exam],
            )
            .await
            .expect("exam");
            conn.execute(
                "INSERT INTO subjects VALUES ('english-language',?1,'English Language',0,0,50,'[]',NULL,NULL)",
                [exam],
            )
            .await
            .expect("subject");
            let slug = format!("{}-comprehension", exam.to_ascii_lowercase());
            conn.execute(
                "INSERT INTO topics VALUES (?1,'english-language',?2,'Comprehension',1,0,'[]','[]','[]')",
                [slug.as_str(), exam],
            )
            .await
            .expect("topic");
        }
        conn.execute(
            "INSERT INTO subtopics VALUES ('comprehension','jamb-comprehension','Comprehension',1,'[]','[]')",
            (),
        )
        .await
        .expect("subtopic");
        conn.execute(
            "UPDATE topics SET lesson_refs=?1 WHERE exam='JAMB'",
            [r#"[{"id":"lesson:a","title":"Old A","order":1},{"id":"lesson:b","title":"B","order":2}]"#],
        )
        .await
        .expect("jamb refs");
        conn.execute(
            "UPDATE topics SET lesson_refs=?1 WHERE exam='WAEC'",
            [r#"[{"id":"lesson:a","title":"Old A","order":1}]"#],
        )
        .await
        .expect("waec refs");
        conn.execute(
            "UPDATE subtopics SET lesson_refs=?1",
            [r#"[{"id":"lesson:a","title":"Old A","order":1}]"#],
        )
        .await
        .expect("subtopic refs");
        for (id, title) in [("lesson:a", "Old A"), ("lesson:b", "B")] {
            conn.execute(
                "INSERT INTO lessons (id,status,title,description,subject,level,estimated_minutes,objectives,content,checks,misconceptions,summary,example_question_refs,provenance,content_hash) VALUES (?1,'published',?2,'{}','english-language','secondary',5,'[]','[]','[]','[]','[]','[]','{}','hash')",
                [id, title],
            )
            .await
            .expect("lesson");
        }

        let bundle = LessonBundle {
            lessons: vec![valid_lesson("lesson:a", "english-language", "New A")],
            topic_links: vec![TopicLessonLink {
                exam: "WAEC".to_string(),
                subject: "english-language".to_string(),
                topic_slug: "waec-comprehension".to_string(),
                subtopic_slug: None,
                lesson_id: "lesson:a".to_string(),
                order_index: 1,
            }],
            example_question_links: Vec::new(),
        };
        import_bundle(&s, &bundle).await.expect("partial import");

        let jamb = syllabus_lesson_refs(&s, "JAMB", "english-language")
            .await
            .expect("jamb refs");
        assert_eq!(jamb.topic("jamb-comprehension").len(), 2);
        assert_eq!(jamb.topic("jamb-comprehension")[0].id, "lesson:a");
        assert_eq!(jamb.topic("jamb-comprehension")[0].title, "New A");
        assert_eq!(jamb.topic("jamb-comprehension")[1].id, "lesson:b");
        assert_eq!(
            jamb.subtopic("jamb-comprehension", "comprehension")[0].id,
            "lesson:a"
        );

        let waec = syllabus_lesson_refs(&s, "WAEC", "english-language")
            .await
            .expect("waec refs");
        assert_eq!(waec.topic("waec-comprehension").len(), 1);
        assert_eq!(waec.topic("waec-comprehension")[0].id, "lesson:a");
    }

    #[tokio::test]
    async fn raw_parent_refs_requires_parent_exam_to_own_topic() {
        let s = db_state(replica().await);
        let conn = conn_of(&s).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &["exams", "subjects", "topics", "subtopics", "questions"],
        )
        .await;
        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','JAMB','[\"NG\"]','active',1,NULL,NULL,'[]')",
            (),
        )
        .await
        .expect("exam");
        conn.execute(
            "INSERT INTO subjects VALUES ('english-language','JAMB','English Language',0,0,50,'[]',NULL,NULL)",
            (),
        )
        .await
        .expect("subject");
        conn.execute(
            "INSERT INTO topics VALUES ('comprehension','english-language','JAMB','Comprehension',1,0,'[]','[]','[]')",
            (),
        )
        .await
        .expect("topic");
        let raw_refs = r#"[{"id":"lesson:jamb","title":"Jamb","order":1}]"#;
        conn.execute(
            "INSERT INTO subtopics VALUES ('intro','comprehension','Intro',1,'[]',?1)",
            [raw_refs],
        )
        .await
        .expect("subtopic");

        let owner = LinkParent {
            exam: "JAMB".to_string(),
            subject: "english-language".to_string(),
            topic_slug: "comprehension".to_string(),
            subtopic_slug: "intro".to_string(),
        };
        assert_eq!(
            raw_parent_refs(&s, &owner).await.expect("owner refs"),
            raw_refs
        );

        let other_exam = LinkParent {
            exam: "WAEC".to_string(),
            ..owner.clone()
        };
        assert_eq!(
            raw_parent_refs(&s, &other_exam)
                .await
                .expect("other exam refs"),
            "[]"
        );

        let other_subject = LinkParent {
            subject: "physics".to_string(),
            ..owner
        };
        assert_eq!(
            raw_parent_refs(&s, &other_subject)
                .await
                .expect("other subject refs"),
            "[]"
        );
    }

    #[tokio::test]
    async fn import_bundle_validates_subject_for_existing_lesson() {
        let s = db_state(replica().await);
        let conn = conn_of(&s).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &["exams", "subjects", "topics", "subtopics", "questions"],
        )
        .await;
        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','JAMB','[\"NG\"]','active',1,NULL,NULL,'[]')",
            (),
        )
        .await
        .expect("exam");
        conn.execute(
            "INSERT INTO subjects VALUES ('english-language','JAMB','English Language',0,0,50,'[]',NULL,NULL)",
            (),
        )
        .await
        .expect("subject");
        conn.execute(
            "INSERT INTO topics VALUES ('comprehension','english-language','JAMB','Comprehension',1,0,'[]','[]','[]')",
            (),
        )
        .await
        .expect("topic");
        conn.execute(
            "INSERT INTO lessons (id,status,title,description,subject,level,estimated_minutes,objectives,content,checks,misconceptions,summary,example_question_refs,provenance,content_hash) VALUES ('lesson:physics','published','Physics','{}','physics','secondary',5,'[]','[]','[]','[]','[]','[]','{}','hash')",
            (),
        )
        .await
        .expect("lesson");

        let bundle = LessonBundle {
            lessons: Vec::new(),
            topic_links: vec![TopicLessonLink {
                exam: "JAMB".to_string(),
                subject: "english-language".to_string(),
                topic_slug: "comprehension".to_string(),
                subtopic_slug: None,
                lesson_id: "lesson:physics".to_string(),
                order_index: 1,
            }],
            example_question_links: Vec::new(),
        };
        match import_bundle(&s, &bundle)
            .await
            .expect_err("subject mismatch")
        {
            AppError::BadRequest(message) => {
                assert!(message.contains("subject does not match"), "{message}")
            }
            other => panic!("expected BadRequest, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn import_bundle_inserts_links_at_authored_position_in_existing_refs() {
        let s = db_state(replica().await);
        let conn = conn_of(&s).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["topics", "subtopics"]).await;
        conn.execute(
            "INSERT INTO topics VALUES ('comprehension','english-language','JAMB','Comprehension',1,0,'[]','[]',?1)",
            [r#"[{"id":"lesson:old","title":"Old","order":1},{"id":"lesson:tail","title":"Tail","order":2}]"#],
        )
        .await
        .expect("topic with existing refs");
        conn.execute(
            "INSERT INTO subtopics VALUES ('intro','comprehension','Intro',1,'[]',?1)",
            [r#"[{"id":"lesson:old","title":"Old","order":1},{"id":"lesson:tail","title":"Tail","order":2}]"#],
        )
        .await
        .expect("subtopic with existing refs");
        for (id, title) in [("lesson:old", "Old"), ("lesson:tail", "Tail")] {
            conn.execute(
                "INSERT INTO lessons (id,status,title,description,subject,level,estimated_minutes,objectives,content,checks,misconceptions,summary,example_question_refs,provenance,content_hash) VALUES (?1,'published',?2,'{}','english-language','secondary',5,'[]','[]','[]','[]','[]','[]','{}','hash')",
                [id, title],
            )
            .await
            .expect("existing lesson");
        }

        let bundle = LessonBundle {
            lessons: vec![valid_lesson("lesson:new", "english-language", "New")],
            topic_links: vec![
                TopicLessonLink {
                    exam: "JAMB".to_string(),
                    subject: "english-language".to_string(),
                    topic_slug: "comprehension".to_string(),
                    subtopic_slug: None,
                    lesson_id: "lesson:new".to_string(),
                    order_index: 1,
                },
                TopicLessonLink {
                    exam: "JAMB".to_string(),
                    subject: "english-language".to_string(),
                    topic_slug: "comprehension".to_string(),
                    subtopic_slug: Some("intro".to_string()),
                    lesson_id: "lesson:new".to_string(),
                    order_index: 1,
                },
            ],
            example_question_links: Vec::new(),
        };
        import_bundle(&s, &bundle).await.expect("import");

        let refs = syllabus_lesson_refs(&s, "JAMB", "english-language")
            .await
            .expect("refs");
        let visible = refs.topic("comprehension");
        let ids: Vec<_> = visible.iter().map(|r| r.id.as_str()).collect();
        assert_eq!(ids, ["lesson:new", "lesson:old", "lesson:tail"]);
        let orders: Vec<_> = visible.iter().map(|r| r.order).collect();
        assert_eq!(orders, [1, 2, 3]);
        let visible_subtopic = refs.subtopic("comprehension", "intro");
        assert_eq!(
            visible_subtopic
                .iter()
                .map(|r| r.id.as_str())
                .collect::<Vec<_>>(),
            ["lesson:new", "lesson:old", "lesson:tail"]
        );

        let mut rows = conn
            .query(
                "SELECT lesson_refs FROM topics WHERE exam='JAMB' AND subject='english-language' AND slug='comprehension'",
                (),
            )
            .await
            .expect("stored refs");
        let raw: String = rows
            .next()
            .await
            .expect("row")
            .expect("result")
            .get(0)
            .expect("json");
        let stored: Vec<ContentReference> = serde_json::from_str(&raw).expect("stored json");
        assert_eq!(
            stored.iter().map(|r| r.id.as_str()).collect::<Vec<_>>(),
            ["lesson:new", "lesson:old", "lesson:tail"]
        );
        assert_eq!(
            stored.iter().map(|r| r.order).collect::<Vec<_>>(),
            [1, 2, 3]
        );
    }

    #[tokio::test]
    async fn duplicate_topic_slug_fails_closed_for_subtopic_refs() {
        let s = db_state(replica().await);
        let conn = conn_of(&s).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &["exams", "subjects", "topics", "subtopics", "questions"],
        )
        .await;
        for exam in ["JAMB", "WAEC"] {
            conn.execute(
                "INSERT INTO exams VALUES (?1,?1,'[\"NG\"]','active',1,NULL,NULL,'[]')",
                [exam],
            )
            .await
            .expect("exam");
            conn.execute(
                "INSERT INTO subjects VALUES ('english-language',?1,'English Language',0,0,50,'[]',NULL,NULL)",
                [exam],
            )
            .await
            .expect("subject");
            conn.execute(
                "INSERT INTO topics VALUES ('comprehension','english-language',?1,'Comprehension',1,0,'[]','[]','[]')",
                [exam],
            )
            .await
            .expect("topic");
        }
        conn.execute(
            "INSERT INTO exams VALUES ('NECO','NECO','[\"NG\"]','active',1,NULL,NULL,'[]')",
            (),
        )
        .await
        .expect("unrelated exam");
        conn.execute(
            "INSERT INTO subjects VALUES ('physics','NECO','Physics',0,0,50,'[]',NULL,NULL)",
            (),
        )
        .await
        .expect("unrelated subject");
        conn.execute(
            "INSERT INTO topics VALUES ('motion','physics','NECO','Motion',1,0,'[]','[]','[]')",
            (),
        )
        .await
        .expect("unrelated topic");
        conn.execute(
            "INSERT INTO subtopics VALUES ('intro','comprehension','Intro',1,'[]','[]')",
            (),
        )
        .await
        .expect("subtopic");

        let topic_bundle = LessonBundle {
            lessons: vec![valid_lesson(
                "lesson:shared",
                "english-language",
                "Shared lesson",
            )],
            topic_links: vec![TopicLessonLink {
                exam: "JAMB".to_string(),
                subject: "english-language".to_string(),
                topic_slug: "comprehension".to_string(),
                subtopic_slug: None,
                lesson_id: "lesson:shared".to_string(),
                order_index: 1,
            }],
            example_question_links: Vec::new(),
        };
        import_bundle(&s, &topic_bundle).await.expect("topic link");

        let subtopic_bundle = LessonBundle {
            lessons: Vec::new(),
            topic_links: vec![TopicLessonLink {
                exam: "WAEC".to_string(),
                subject: "english-language".to_string(),
                topic_slug: "comprehension".to_string(),
                subtopic_slug: Some("intro".to_string()),
                lesson_id: "lesson:shared".to_string(),
                order_index: 1,
            }],
            example_question_links: Vec::new(),
        };
        match import_bundle(&s, &subtopic_bundle)
            .await
            .expect_err("ambiguous subtopic owner")
        {
            AppError::Internal(message) => {
                assert!(message.contains("multiple syllabus owners"), "{message}")
            }
            other => panic!("expected Internal, got {other:?}"),
        }

        let mut rows = conn
            .query(
                "SELECT COALESCE(lesson_refs,'[]') FROM subtopics WHERE topic='comprehension' AND slug='intro'",
                (),
            )
            .await
            .expect("subtopic refs");
        let raw: String = rows
            .next()
            .await
            .expect("row")
            .expect("result")
            .get(0)
            .expect("json");
        assert_eq!(raw, "[]");

        match syllabus_lesson_refs(&s, "JAMB", "english-language").await {
            Err(AppError::Internal(message)) => {
                assert!(message.contains("multiple syllabus owners"), "{message}")
            }
            other => panic!("expected a fail-closed read, got {other:?}"),
        }
        let unrelated = syllabus_lesson_refs(&s, "NECO", "physics")
            .await
            .expect("unrelated syllabus still reads");
        assert!(unrelated.topic("motion").is_empty());
    }

    #[tokio::test]
    async fn import_bundle_keeps_bundle_lessons_without_a_link_on_that_parent() {
        let s = db_state(replica().await);
        let conn = conn_of(&s).await;
        api_schema(&conn).await;
        bank_schema(&conn, &["topics", "subtopics"]).await;
        conn.execute(
            "INSERT INTO topics VALUES ('comprehension','english-language','JAMB','Comprehension',1,0,'[]','[]',?1)",
            [r#"[{"id":"lesson:a","title":"Old A","order":1}]"#],
        )
        .await
        .expect("topic with existing ref");
        conn.execute(
            "INSERT INTO lessons (id,status,title,description,subject,level,estimated_minutes,objectives,content,checks,misconceptions,summary,example_question_refs,provenance,content_hash) VALUES ('lesson:a','published','Old A','{}','english-language','secondary',5,'[]','[]','[]','[]','[]','[]','{}','hash')",
            (),
        )
        .await
        .expect("existing lesson");

        let bundle = LessonBundle {
            lessons: vec![
                valid_lesson("lesson:a", "english-language", "New A"),
                valid_lesson("lesson:c", "english-language", "C"),
            ],
            topic_links: vec![TopicLessonLink {
                exam: "JAMB".to_string(),
                subject: "english-language".to_string(),
                topic_slug: "comprehension".to_string(),
                subtopic_slug: None,
                lesson_id: "lesson:c".to_string(),
                order_index: 1,
            }],
            example_question_links: Vec::new(),
        };
        import_bundle(&s, &bundle).await.expect("partial import");

        let refs = syllabus_lesson_refs(&s, "JAMB", "english-language")
            .await
            .expect("refs");
        let visible = refs.topic("comprehension");
        assert_eq!(
            visible.iter().map(|r| r.id.as_str()).collect::<Vec<_>>(),
            ["lesson:c", "lesson:a"]
        );
        assert_eq!(visible[1].title, "New A");
    }

    #[tokio::test]
    async fn import_bundle_rejects_zero_order_index() {
        let s = db_state(replica().await);
        let bundle = LessonBundle {
            lessons: Vec::new(),
            topic_links: vec![TopicLessonLink {
                exam: "JAMB".to_string(),
                subject: "english-language".to_string(),
                topic_slug: "comprehension".to_string(),
                subtopic_slug: None,
                lesson_id: "lesson:one".to_string(),
                order_index: 0,
            }],
            example_question_links: Vec::new(),
        };
        match import_bundle(&s, &bundle)
            .await
            .expect_err("zero is not a one-based position")
        {
            AppError::BadRequest(message) => {
                assert!(message.contains("order_index below 1"), "{message}")
            }
            other => panic!("expected BadRequest, got {other:?}"),
        }
    }
}
