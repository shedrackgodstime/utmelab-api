//! Turso writers for review and import (W1/W2).
//!
//! Reads go through [`TursoStore`]; writes come here. Every writer computes
//! `content_hash` with the shared [`Question::content_fingerprint`] (R6) and
//! upserts by id. Validation always happens *before* any call here, through
//! [`JsonStore::check_new_questions`] or the review gates — a writer that
//! finds a problem refuses; it never filters silently.

use crate::bank::Question;
use crate::db::Db;
use crate::error::ApiError;

fn internal(ctx: &str, e: impl std::fmt::Display) -> ApiError {
    ApiError::Internal(format!("turso write {ctx}: {e}"))
}

/// Retry a fallible async op with backoff. Upserts are idempotent, so
/// retrying is always safe.
macro_rules! retry {
    ($label:expr, $tries:expr, $op:expr) => {{
        let mut attempt = 0u32;
        loop {
            attempt += 1;
            match $op.await {
                Ok(v) => break v,
                Err(e) => {
                    if attempt >= $tries {
                        return Err(internal($label, e.to_string()));
                    }
                    tracing::warn!("turso write {} failed, retrying: {}", $label, e.to_string());
                    std::thread::sleep(std::time::Duration::from_secs(1 << attempt.min(4)));
                }
            }
        }
    }};
}

/// Upsert validated questions. POSTcondition: every row carries a fresh
/// fingerprint; callers must have run the R4 gate first.
pub async fn upsert_questions(db: &Db, questions: &[Question]) -> Result<usize, ApiError> {
    use turso_serverless::Value::{Integer, Null, Real, Text};
    let text_of = |v: Option<&str>| v.map(|s| Text(s.to_owned())).unwrap_or(Null);
    for (i, q) in questions.iter().enumerate() {
        let inline = serde_json::to_string(&q.text.inline).unwrap_or_else(|_| "[]".to_string());
        let options = serde_json::to_string(&q.options).unwrap_or_else(|_| "[]".to_string());
        let explanation = q
            .explanation
            .as_ref()
            .map(|e| serde_json::to_string(e).unwrap_or_else(|_| "null".to_string()));
        let hash = q.content_fingerprint();
        // 17 params exceeds the driver's 16-tuple impl, so a Vec it is.
        // text_norm rides along: Rust-lowercased once here, matched by ?q=.
        let params = vec![
            Text(q.id.clone()),
            Text(q.exam.clone()),
            Text(q.subject.clone()),
            Integer(q.year as i64),
            Text(q.source.clone()),
            Text(q.text.text.clone()),
            Text(inline),
            Text(options),
            Text(q.answer.clone()),
            text_of(q.subtopic_id.as_deref()),
            text_of(q.section.as_deref()),
            text_of(q.passage_id.as_deref()),
            text_of(explanation.as_deref()),
            Real(q.marks as f64),
            Integer(q.difficulty as i64),
            Text(hash),
            Text(q.text.text.to_lowercase()),
        ];
        retry!(
            "upsert-question",
            6,
            db.conn().execute(
                "INSERT INTO questions(id,exam,subject,year,source,text,inline,options,answer,subtopic_id,section,passage_id,explanation,marks,difficulty,content_hash,text_norm) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17) ON CONFLICT(id) DO UPDATE SET exam=excluded.exam,subject=excluded.subject,year=excluded.year,source=excluded.source,text=excluded.text,inline=excluded.inline,options=excluded.options,answer=excluded.answer,subtopic_id=excluded.subtopic_id,section=excluded.section,passage_id=excluded.passage_id,explanation=excluded.explanation,marks=excluded.marks,difficulty=excluded.difficulty,content_hash=excluded.content_hash,text_norm=excluded.text_norm",
                params.clone(),
            )
        );
        if (i + 1) % 100 == 0 {
            tracing::info!("turso upserted {}/{} questions", i + 1, questions.len());
        }
    }
    Ok(questions.len())
}
