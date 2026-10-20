//! Per-request question reads (D74 phase 1).
//!
//! Indexed SQL with `LIMIT/OFFSET` instead of scanning an in-RAM bank. The
//! contract is byte-identical to `Store::questions_page` / `Store::question`:
//! same order (id ascending, byte-wise), same filters, same totals. Proven
//! by parity tests against `JsonStore`, never by inspection.
//!
//! Two deliberate choices:
//! * `verified` derives in Rust from a batched verifications read, exactly
//!   like the build path (`human_verified`). The `verified=true` *filter*
//!   is SQL (an `EXISTS` spelling of the same rule) because paging needs
//!   totals the filter shapes.
//! * `?q=` matches `text_norm`, lowercased once in Rust at seed time.
//!   Turso `LOWER()` is ASCII-only and would silently change results on
//!   diacritics (measured); the column keeps both sides on one function.

use crate::bank::model::{Choice, Explanation, Question, RichText, Verification, human_verified};
use crate::bank::store::{MAX_PER_PAGE, QuestionFilter, QuestionPage};
use crate::error::ApiError;

const PAGE_COLUMNS: &str = "id,exam,subject,year,source,text,inline,options,\
    answer,subtopic_id,section,passage_id,explanation,marks,difficulty";

/// A read handle over any libsql database: local file in tests, remote in
/// production. One `connect()` per call — handles are cheap, queries carry
/// no session state.
#[derive(Debug)]
pub struct SqlReads {
    db: libsql::Database,
}

impl SqlReads {
    pub fn new(db: libsql::Database) -> Self {
        Self { db }
    }

    /// Same contract as `Store::questions_page`: clamped paging, id order,
    /// totals over the filtered set.
    pub async fn questions_page(
        &self,
        filter: QuestionFilter<'_>,
        page: u32,
        per_page: u32,
    ) -> Result<QuestionPage, ApiError> {
        let per_page = per_page.clamp(1, MAX_PER_PAGE);
        let page = page.max(1);
        let offset = (page - 1) * per_page;

        let where_sql = where_clause();
        let conn = self
            .conn()
            .await
            .map_err(|e| ApiError::internal(format!("reads connect: {e}")))?;

        let total: i64 = {
            let sql = format!("SELECT COUNT(*) FROM questions q WHERE {where_sql}");
            let mut rows = conn
                .query(&sql, params(&filter))
                .await
                .map_err(|e| ApiError::internal(format!("reads count: {e}")))?;
            rows.next()
                .await
                .map_err(|e| ApiError::internal(format!("reads count row: {e}")))?
                .ok_or_else(|| ApiError::internal("reads count: no row"))?
                .get(0)
                .map_err(|e| ApiError::internal(format!("reads count value: {e}")))?
        };

        let sql = format!(
            "SELECT {PAGE_COLUMNS} FROM questions q WHERE {where_sql} \
             ORDER BY q.id ASC LIMIT ? OFFSET ?"
        );
        let mut p = params(&filter);
        p.push(libsql::Value::Integer(per_page as i64));
        p.push(libsql::Value::Integer(offset as i64));
        let mut rows = conn
            .query(&sql, p)
            .await
            .map_err(|e| ApiError::internal(format!("reads page: {e}")))?;
        let mut questions = Vec::new();
        while let Some(row) = rows
            .next()
            .await
            .map_err(|e| ApiError::internal(format!("reads row: {e}")))?
        {
            questions.push(question_from_row(&row)?);
        }

        derive_verified(&conn, &mut questions).await?;

        Ok(QuestionPage {
            questions,
            page,
            per_page,
            total_records: total.max(0) as usize,
        })
    }

    /// Same contract as `Store::question`: one row by id, verified derived.
    pub async fn question_by_id(&self, id: &str) -> Result<Option<Question>, ApiError> {
        let conn = self
            .conn()
            .await
            .map_err(|e| ApiError::internal(format!("reads connect: {e}")))?;
        let mut rows = conn
            .query(
                &format!("SELECT {PAGE_COLUMNS} FROM questions WHERE id = ?1 AND exam <> ''"),
                vec![libsql::Value::Text(id.to_owned())],
            )
            .await
            .map_err(|e| ApiError::internal(format!("reads by id: {e}")))?;
        let Some(row) = rows
            .next()
            .await
            .map_err(|e| ApiError::internal(format!("reads by id row: {e}")))?
        else {
            return Ok(None);
        };
        let mut question = question_from_row(&row)?;
        derive_verified(&conn, std::slice::from_mut(&mut question)).await?;
        Ok(Some(question))
    }

    async fn conn(&self) -> Result<libsql::Connection, libsql::Error> {
        self.db.connect()
    }
}

/// The shared WHERE fragment, positional params `?1..=?18` in fixed order:
/// exam x2, subject x2, subtopic x2, source x2, year x2, text x2,
/// country x4, verified x2. (Repeated filters need one value per use.)
/// Withheld rows (empty exam) are excluded up front: valid records
/// the bank keeps beside the servable set, never served (D21/D58).
fn where_clause() -> &'static str {
    "(q.exam <> '')
     AND (?1 IS NULL OR q.exam = ?2)
     AND (?3 IS NULL OR q.subject = ?4)
     AND (?5 IS NULL OR q.subtopic_id = ?6)
     AND (?7 IS NULL OR q.source = ?8)
     AND (?9 IS NULL OR q.year = ?10)
     AND (?11 IS NULL OR q.text_norm LIKE '%' || ?12 || '%' ESCAPE '\\')
     AND (?13 IS NULL OR q.subtopic_id IS NULL
       OR NOT EXISTS (SELECT 1 FROM subtopics st WHERE st.slug = q.subtopic_id)
       OR NOT EXISTS (SELECT 1 FROM topic_countries tc
         WHERE tc.topic = (SELECT st.topic FROM subtopics st WHERE st.slug = q.subtopic_id))
       OR EXISTS (SELECT 1 FROM topic_countries tc
         WHERE tc.topic = (SELECT st.topic FROM subtopics st WHERE st.slug = q.subtopic_id)
         AND tc.country = ?14))
     AND (?15 IS NULL OR (?15 = 1) = EXISTS (
       SELECT 1 FROM verifications v
       WHERE v.question_id = q.id AND v.kind = 'human' AND v.verdict = 'pass'
       AND v.content_hash = q.content_hash
       AND EXISTS (SELECT 1 FROM json_each(v.scope) WHERE value = 'answer')
       AND EXISTS (SELECT 1 FROM json_each(v.scope) WHERE value = 'explanation')
       AND NOT EXISTS (
         SELECT 1 FROM verifications v2
         WHERE v2.question_id = v.question_id AND v2.kind = 'human'
         AND (v2.created_at, v2.id) > (v.created_at, v.id)
         AND EXISTS (SELECT 1 FROM json_each(v2.scope) WHERE value = 'answer')
         AND EXISTS (SELECT 1 FROM json_each(v2.scope) WHERE value = 'explanation'))))"
}

/// Positional params matching the WHERE fragment above.
fn params(filter: &QuestionFilter<'_>) -> Vec<libsql::Value> {
    use libsql::Value::{Integer, Null, Text};
    let opt = |v: Option<&str>| v.map(|s| Text(s.to_owned())).unwrap_or(Null);
    let year = filter.year.map(|y| Integer(y as i64)).unwrap_or(Null);
    let text = filter
        .text
        .map(|q| Text(escape_like(&q.to_lowercase())))
        .unwrap_or(Null);
    let country = opt(filter.country);
    let verified = filter
        .verified
        .map(|v| Integer(i32::from(v) as i64))
        .unwrap_or(Null);
    vec![
        opt(filter.exam),
        opt(filter.exam),
        opt(filter.subject),
        opt(filter.subject),
        opt(filter.subtopic),
        opt(filter.subtopic),
        opt(filter.source),
        opt(filter.source),
        year.clone(),
        year,
        text.clone(),
        text,
        country.clone(),
        country,
        verified,
    ]
}

/// `\, `%` and `_` are literal in the needle; the query declares `ESCAPE '\'`.
fn escape_like(needle: &str) -> String {
    let mut out = String::with_capacity(needle.len());
    for ch in needle.chars() {
        if matches!(ch, '\\' | '%' | '_') {
            out.push('\\');
        }
        out.push(ch);
    }
    out
}

fn question_from_row(row: &libsql::Row) -> Result<Question, ApiError> {
    let bad = |field: &str, msg: String| ApiError::internal(format!("reads row {field}: {msg}"));
    let text: String = row.get(5).map_err(|e| bad("text", e.to_string()))?;
    let inline: String = row.get(6).map_err(|e| bad("inline", e.to_string()))?;
    let options: String = row.get(7).map_err(|e| bad("options", e.to_string()))?;
    let explanation: Option<String> = row.get(12).map_err(|e| bad("explanation", e.to_string()))?;
    Ok(Question {
        id: row.get(0).map_err(|e| bad("id", e.to_string()))?,
        exam: row.get(1).map_err(|e| bad("exam", e.to_string()))?,
        subject: row.get(2).map_err(|e| bad("subject", e.to_string()))?,
        year: row.get::<i64>(3).map_err(|e| bad("year", e.to_string()))? as u16,
        source: row.get(4).map_err(|e| bad("source", e.to_string()))?,
        text: RichText {
            text,
            inline: serde_json::from_str(&inline).map_err(|e| bad("inline", e.to_string()))?,
        },
        options: serde_json::from_str::<Vec<Choice>>(&options)
            .map_err(|e| bad("options", e.to_string()))?,
        answer: row.get(8).map_err(|e| bad("answer", e.to_string()))?,
        subtopic_id: row.get(9).map_err(|e| bad("subtopic_id", e.to_string()))?,
        section: row.get(10).map_err(|e| bad("section", e.to_string()))?,
        passage_id: row.get(11).map_err(|e| bad("passage_id", e.to_string()))?,
        explanation: explanation
            .map(|s: String| {
                serde_json::from_str::<Explanation>(&s)
                    .map_err(|e| bad("explanation", e.to_string()))
            })
            .transpose()?,
        marks: row
            .get::<f64>(13)
            .map_err(|e| bad("marks", e.to_string()))? as f32,
        difficulty: row
            .get::<i64>(14)
            .map_err(|e| bad("difficulty", e.to_string()))? as u8,
        verified: false,
    })
}

/// Derive `verified` for page rows from one batched verifications read —
/// the same `human_verified` rule the build path runs, never a stored flag.
async fn derive_verified(
    conn: &libsql::Connection,
    questions: &mut [Question],
) -> Result<(), ApiError> {
    if questions.is_empty() {
        return Ok(());
    }
    // One IN-list per call site; pages cap at 200 rows by construction.
    let mut sql = String::from(
        "SELECT id,question_id,kind,verdict,scope,verifier,detail,content_hash,created_at \
         FROM verifications WHERE question_id IN (",
    );
    for (i, _) in questions.iter().enumerate() {
        if i > 0 {
            sql.push_str(", ");
        }
        sql.push_str(&format!("?{}", i + 1));
    }
    sql.push(')');
    let ids: Vec<libsql::Value> = questions
        .iter()
        .map(|q| libsql::Value::Text(q.id.clone()))
        .collect();
    let mut rows = conn
        .query(&sql, ids)
        .await
        .map_err(|e| ApiError::internal(format!("reads verifications: {e}")))?;
    let mut by_question: std::collections::HashMap<String, Vec<Verification>> =
        std::collections::HashMap::new();
    while let Some(row) = rows
        .next()
        .await
        .map_err(|e| ApiError::internal(format!("reads verification row: {e}")))?
    {
        let bad = |field: &str, msg: String| {
            ApiError::internal(format!("reads verification {field}: {msg}"))
        };
        // kind/verdict ride bare in the table; the enums parse quoted.
        let kind: String = row.get(2).map_err(|e| bad("kind", e.to_string()))?;
        let verdict: String = row.get(3).map_err(|e| bad("verdict", e.to_string()))?;
        let scope: String = row.get(4).map_err(|e| bad("scope", e.to_string()))?;
        let verification = Verification {
            id: row.get(0).map_err(|e| bad("id", e.to_string()))?,
            question_id: row.get(1).map_err(|e| bad("question_id", e.to_string()))?,
            kind: serde_json::from_str(&format!("\"{kind}\""))
                .map_err(|e| bad("kind", e.to_string()))?,
            verdict: serde_json::from_str(&format!("\"{verdict}\""))
                .map_err(|e| bad("verdict", e.to_string()))?,
            scope: serde_json::from_str(&scope).map_err(|e| bad("scope", e.to_string()))?,
            verifier: row.get(5).map_err(|e| bad("verifier", e.to_string()))?,
            detail: row.get(6).map_err(|e| bad("detail", e.to_string()))?,
            content_hash: row.get(7).map_err(|e| bad("content_hash", e.to_string()))?,
            created_at: row.get(8).map_err(|e| bad("created_at", e.to_string()))?,
        };
        by_question
            .entry(verification.question_id.clone())
            .or_default()
            .push(verification);
    }
    for q in questions.iter_mut() {
        let empty = Vec::new();
        let log = by_question.get(&q.id).unwrap_or(&empty);
        q.verified = human_verified(log, &q.id, &q.content_fingerprint());
    }
    Ok(())
}
