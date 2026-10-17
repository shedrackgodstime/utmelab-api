//! Gated local reads. Every function here holds a gate permit for its
//! duration and retries transient lock contention, so bursts degrade to
//! fast 503s instead of wedging workers.

use super::{upstream, with_conn};
use crate::{core, error::AppError, state::DbState};

/// Names a key may see. The SQL no longer carries a deny list: a name that is
/// not in the `core` allowlist is dropped here, so an engine table such as
/// `__turso_internal_mvcc_meta` (whose leading `__turso_` a deny list missed)
/// can never be listed.
pub async fn fetch_table_names(s: &DbState) -> Result<Vec<String>, AppError> {
    with_conn(s, |conn| async move {
        let mut rows = conn
            .query("SELECT name FROM sqlite_master WHERE type='table'", ())
            .await
            .map_err(upstream)?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().await.map_err(upstream)? {
            let name: String = row.get(0).map_err(upstream)?;
            if core::catalog::is_introspectable(&name) {
                out.push(name);
            }
        }
        out.sort();
        Ok(out)
    })
    .await
}

/// Single composer for "list local tables". Both `api` and `mcp` call this;
/// the mapping itself stays in `core` so surfaces never duplicate it.
pub async fn table_refs(s: &DbState) -> Result<Vec<core::models::TableRef>, AppError> {
    Ok(core::catalog::to_refs(fetch_table_names(s).await?))
}

fn opt_bool(v: turso::Value) -> Result<Option<bool>, AppError> {
    match v {
        turso::Value::Null => Ok(None),
        turso::Value::Integer(n) => Ok(Some(n != 0)),
        _ => Err(AppError::Upstream(
            "exam flag column is not an integer".to_string(),
        )),
    }
}

fn opt_u32(v: turso::Value) -> Result<Option<u32>, AppError> {
    match v {
        turso::Value::Null => Ok(None),
        turso::Value::Integer(n) => Ok(Some(n as u32)),
        _ => Err(AppError::Upstream(
            "exam count column is not an integer".to_string(),
        )),
    }
}

fn opt_u16(v: turso::Value) -> Result<Option<u16>, AppError> {
    match v {
        turso::Value::Null => Ok(None),
        turso::Value::Integer(n) => u16::try_from(n)
            .map(Some)
            .map_err(|_| AppError::Upstream("column out of u16 range".to_string())),
        _ => Err(AppError::Upstream("column is not an integer".to_string())),
    }
}

fn opt_u8(v: turso::Value) -> Result<Option<u8>, AppError> {
    match v {
        turso::Value::Null => Ok(None),
        turso::Value::Integer(n) => u8::try_from(n)
            .map(Some)
            .map_err(|_| AppError::Upstream("column out of u8 range".to_string())),
        _ => Err(AppError::Upstream("column is not an integer".to_string())),
    }
}

fn json_col<T: serde::de::DeserializeOwned>(raw: &str, col: &'static str) -> Result<T, AppError> {
    serde_json::from_str(raw).map_err(|e| AppError::Upstream(format!("{col}: {e}")))
}

fn json_list(raw: &str, col: &'static str) -> Result<Vec<String>, AppError> {
    json_col(raw, col)
}

fn opt_string(v: turso::Value) -> Result<Option<String>, AppError> {
    match v {
        turso::Value::Null => Ok(None),
        turso::Value::Text(t) => Ok(Some(t)),
        _ => Err(AppError::Upstream(
            "question text column is not text".to_string(),
        )),
    }
}

fn req_u16(v: turso::Value, col: &'static str) -> Result<u16, AppError> {
    match v {
        turso::Value::Integer(n) => {
            u16::try_from(n).map_err(|_| AppError::Upstream(format!("{col} out of range")))
        }
        _ => Err(AppError::Upstream(format!("{col} is not an integer"))),
    }
}

fn req_u8(v: turso::Value, col: &'static str) -> Result<u8, AppError> {
    match v {
        turso::Value::Integer(n) => {
            u8::try_from(n).map_err(|_| AppError::Upstream(format!("{col} out of range")))
        }
        _ => Err(AppError::Upstream(format!("{col} is not an integer"))),
    }
}

fn req_f32(v: turso::Value, col: &'static str) -> Result<f32, AppError> {
    match v {
        turso::Value::Real(f) => Ok(f as f32),
        turso::Value::Integer(n) => Ok(n as f32),
        _ => Err(AppError::Upstream(format!("{col} is not a number"))),
    }
}

/// The SQLite engine only ever hands back 0/1 for a boolean expression;
/// anything else is corruption, not a truthy value.
fn req_bool(v: turso::Value, col: &'static str) -> Result<bool, AppError> {
    match v {
        turso::Value::Integer(0) => Ok(false),
        turso::Value::Integer(1) => Ok(true),
        _ => Err(AppError::Upstream(format!("{col} is not 0/1"))),
    }
}

fn opt_f64(v: turso::Value, col: &'static str) -> Result<Option<f64>, AppError> {
    match v {
        turso::Value::Null => Ok(None),
        turso::Value::Real(f) => Ok(Some(f)),
        turso::Value::Integer(n) => Ok(Some(n as f64)),
        _ => Err(AppError::Upstream(format!("{col} is not a number"))),
    }
}

/// Measured expectations for one exam subject. Empty where no rows
/// exist — absence is honest, never 404.
pub async fn list_blueprints(
    s: &DbState,
    exam: &str,
    subject: &str,
) -> Result<Vec<core::models::Blueprint>, AppError> {
    let exam = exam.to_string();
    let subject = subject.to_string();
    with_conn(s, |conn| {
        let exam = exam.clone();
        let subject = subject.clone();
        async move {
            let mut stmt = conn
            .prepare("SELECT exam,subject,level,topic,section,members,paper_size,pct,pct_low,pct_high,expected,expected_low,expected_high,source,sample,method,confidence,status,note FROM blueprints WHERE exam=?1 AND subject=?2")
            .await
            .map_err(upstream)?;
            let mut rows = stmt
                .query([exam.as_str(), subject.as_str()])
                .await
                .map_err(upstream)?;
            let mut out = Vec::new();
            while let Some(row) = rows.next().await.map_err(upstream)? {
                let members_raw: String = row.get(5).map_err(upstream)?;
                out.push(core::models::Blueprint {
                    exam: row.get(0).map_err(upstream)?,
                    subject: row.get(1).map_err(upstream)?,
                    level: row.get(2).map_err(upstream)?,
                    topic: opt_string(row.get_value(3).map_err(upstream)?)?,
                    section: opt_string(row.get_value(4).map_err(upstream)?)?,
                    members: json_col(&members_raw, "blueprint.members")?,
                    paper_size: req_u32(row.get_value(6).map_err(upstream)?, "blueprint.paper_size")?,
                    pct: opt_f64(row.get_value(7).map_err(upstream)?, "blueprint.pct")?,
                    pct_low: opt_f64(row.get_value(8).map_err(upstream)?, "blueprint.pct_low")?,
                    pct_high: opt_f64(row.get_value(9).map_err(upstream)?, "blueprint.pct_high")?,
                    expected: opt_f64(row.get_value(10).map_err(upstream)?, "blueprint.expected")?,
                    expected_low: opt_f64(row.get_value(11).map_err(upstream)?, "blueprint.expected_low")?,
                    expected_high: opt_f64(row.get_value(12).map_err(upstream)?, "blueprint.expected_high")?,
                    source: opt_string(row.get_value(13).map_err(upstream)?)?,
                    sample: opt_string(row.get_value(14).map_err(upstream)?)?,
                    method: row.get(15).map_err(upstream)?,
                    confidence: opt_string(row.get_value(16).map_err(upstream)?)?,
                    status: row.get(17).map_err(upstream)?,
                    note: opt_string(row.get_value(18).map_err(upstream)?)?.unwrap_or_default(),
                });
            }
            Ok(out)
        }
    })
    .await
}

/// One row → one `Question`. Shared by every reader of the questions
/// table so the mapping is written exactly once.
fn map_question(row: &turso::Row) -> Result<core::models::Question, AppError> {
    let text_raw: String = row.get(5).map_err(upstream)?;
    let inline_raw: String = row.get(6).map_err(upstream)?;
    let options_raw: String = row.get(7).map_err(upstream)?;
    Ok(core::models::Question {
        id: row.get(0).map_err(upstream)?,
        exam: row.get(1).map_err(upstream)?,
        subject: row.get(2).map_err(upstream)?,
        year: req_u16(row.get_value(3).map_err(upstream)?, "question.year")?,
        source: row.get(4).map_err(upstream)?,
        text: core::models::RichText {
            text: text_raw,
            inline: json_col(&inline_raw, "question.inline")?,
        },
        options: json_col(&options_raw, "question.options")?,
        answer: row.get(8).map_err(upstream)?,
        subtopic_id: opt_string(row.get_value(9).map_err(upstream)?)?,
        section: opt_string(row.get_value(10).map_err(upstream)?)?,
        passage_id: opt_string(row.get_value(11).map_err(upstream)?)?,
        explanation: match row.get_value(12).map_err(upstream)? {
            turso::Value::Null => None,
            turso::Value::Text(s) => Some(json_col(&s, "question.explanation")?),
            _ => {
                return Err(AppError::Upstream(
                    "question.explanation is not text".to_string(),
                ))
            }
        },
        marks: req_f32(row.get_value(13).map_err(upstream)?, "question.marks")?,
        difficulty: req_u8(row.get_value(14).map_err(upstream)?, "question.difficulty")?,
        verified: req_bool(row.get_value(15).map_err(upstream)?, "question.verified")?,
    })
}

/// Filters over the questions table. `country` is deliberately absent: it
/// needs a `topic_countries` join this slice cannot verify, and a silently
/// ignored filter is worse than a loud rejection (the handler 400s it).
#[derive(Clone, Debug, Default)]
pub struct QuestionFilter {
    pub exam: Option<String>,
    pub subject: Option<String>,
    pub subtopic_id: Option<String>,
    pub year: Option<u16>,
    pub source: Option<String>,
    pub text: Option<String>,
    pub verified: Option<bool>,
}

/// D62's rule, spelled once. `table` is a compile-time literal from this
/// module (never user input), so interpolating it is safe. The outer row is
/// matched by `table.id`/`table.content_hash`, which both `questions` and
/// `novel_questions` carry; the same predicate feeds the `verified` column
/// and the `verified` filter, so the two can never disagree.
fn verified_predicate(table: &str) -> String {
    format!(
        "EXISTS (SELECT 1 FROM verifications v \
         WHERE v.question_id = {table}.id AND v.kind='human' AND v.verdict='pass' \
         AND v.content_hash = {table}.content_hash \
         AND EXISTS (SELECT 1 FROM json_each(v.scope) WHERE value='answer') \
         AND EXISTS (SELECT 1 FROM json_each(v.scope) WHERE value='explanation') \
         AND NOT EXISTS (SELECT 1 FROM verifications v2 \
           WHERE v2.question_id = v.question_id AND v2.kind='human' \
           AND (v2.created_at, v2.id) > (v.created_at, v.id) \
           AND EXISTS (SELECT 1 FROM json_each(v2.scope) WHERE value='answer') \
           AND EXISTS (SELECT 1 FROM json_each(v2.scope) WHERE value='explanation')))"
    )
}

/// Countries a topic belongs to (D19): a topic with no `topic_countries`
/// rows is in every country; one that lists countries is in only those.
/// Expressed as SQL over `questions` so scope is one predicate rather than
/// a second code path per reader. The bound param (NULL = unscoped) is
/// supplied by `scope_param`.
///
/// The table is empty today, so this excludes nothing — it is here so the
/// moment the bank states topic scope, every reader honours it without a
/// rewrite.
fn scope_predicate(param: u8) -> String {
    format!(
        "(?{p} IS NULL OR NOT EXISTS (SELECT 1 FROM topic_countries tc WHERE tc.topic = (SELECT st.topic FROM subtopics st WHERE st.slug = questions.subtopic_id)) OR EXISTS (SELECT 1 FROM topic_countries tc WHERE tc.topic = (SELECT st.topic FROM subtopics st WHERE st.slug = questions.subtopic_id) AND tc.country = ?{p}))",
        p = param
    )
}

/// The scope predicate's bound value: the asked country, or NULL for the
/// unscoped view.
fn scope_param(country: &Option<String>) -> turso::Value {
    match country {
        Some(c) => turso::Value::Text(c.clone()),
        None => turso::Value::Null,
    }
}

/// Escape LIKE wildcards so a consumer typing `%` searches a literal
/// percent instead of matching everything.
fn like_literal(q: &str) -> String {
    let mut out = String::with_capacity(q.len() + 2);
    out.push('%');
    for c in q.chars() {
        if c == '%' || c == '_' || c == '\\' {
            out.push('\\');
        }
        out.push(c);
    }
    out.push('%');
    out
}

/// Shared WHERE clause plus bound params for the count and page queries.
/// Pure and unit-tested: both queries must filter identically, and the
/// only way to guarantee that is one builder.
fn question_where(f: &QuestionFilter) -> (String, Vec<turso::Value>) {
    let mut conds: Vec<String> = Vec::new();
    let mut params = Vec::new();
    if let Some(v) = &f.exam {
        conds.push("exam=?".to_string());
        params.push(turso::Value::Text(v.clone()));
    }
    if let Some(v) = &f.subject {
        conds.push("subject=?".to_string());
        params.push(turso::Value::Text(v.clone()));
    }
    if let Some(v) = &f.subtopic_id {
        conds.push("subtopic_id=?".to_string());
        params.push(turso::Value::Text(v.clone()));
    }
    if let Some(v) = f.year {
        conds.push("year=?".to_string());
        params.push(turso::Value::Integer(v as i64));
    }
    if let Some(v) = &f.source {
        conds.push("source=?".to_string());
        params.push(turso::Value::Text(v.clone()));
    }
    if let Some(v) = &f.text {
        conds.push("text LIKE ? ESCAPE '\\'".to_string());
        params.push(turso::Value::Text(like_literal(v)));
    }
    if let Some(v) = f.verified {
        conds.push(format!("({}) = ?", verified_predicate("questions")));
        params.push(turso::Value::Integer(i32::from(v) as i64));
    }
    if let Some(v) = f.verified {
        conds.push(format!("({}) = ?", verified_predicate("questions")));
        params.push(turso::Value::Integer(i32::from(v) as i64));
    }
    let clause = if conds.is_empty() {
        String::new()
    } else {
        format!(" WHERE {}", conds.join(" AND "))
    };
    (clause, params)
}

/// One page of questions in id order, plus the filtered total. Page
/// numbers below 1 count as 1; page sizes clamp to 1–200.
pub async fn list_questions(
    s: &DbState,
    filter: &QuestionFilter,
    page: u32,
    per_page: u32,
) -> Result<(Vec<core::models::Question>, usize), AppError> {
    let (page, per_page) = core::catalog::page_bounds(page, per_page);
    let (clause, params) = question_where(filter);
    let count_sql = format!("SELECT COUNT(*) FROM questions{clause}");
    let page_sql = format!(
        "SELECT id,exam,subject,year,source,text,inline,options,answer,subtopic_id,section,passage_id,explanation,marks,difficulty, ({}) AS verified FROM questions{clause} ORDER BY id LIMIT {} OFFSET {}",
        verified_predicate("questions"),
        per_page,
        (page - 1) * per_page
    );
    with_conn(s, |conn| {
        let count_sql = count_sql.clone();
        let page_sql = page_sql.clone();
        let params = params.clone();
        async move {
            let total: i64 = conn
                .query(&count_sql, params.clone())
                .await
                .map_err(upstream)?
                .next()
                .await
                .map_err(upstream)?
                .and_then(|r| r.get(0).ok())
                .unwrap_or(0);
            let mut rows = conn.query(&page_sql, params).await.map_err(upstream)?;
            let mut out = Vec::new();
            while let Some(row) = rows.next().await.map_err(upstream)? {
                out.push(map_question(&row)?);
            }
            Ok((out, total as usize))
        }
    })
    .await
}

/// True when this exam offers this subject. Powers the honest 404: a
/// filter naming a combination the bank never had must not return a
/// confident empty list.
pub async fn subject_exists(s: &DbState, exam: &str, slug: &str) -> Result<bool, AppError> {
    let exam = exam.to_string();
    let slug = slug.to_string();
    with_conn(s, |conn| {
        let exam = exam.clone();
        let slug = slug.clone();
        async move {
            let mut stmt = conn
                .prepare("SELECT 1 FROM subjects WHERE exam=?1 AND slug=?2 LIMIT 1")
                .await
                .map_err(upstream)?;
            let hit = stmt
                .query([exam.as_str(), slug.as_str()])
                .await
                .map_err(upstream)?
                .next()
                .await
                .map_err(upstream)?
                .is_some();
            Ok(hit)
        }
    })
    .await
}

/// Map one passage row. Shared by every passage reader so the
/// rich-text assembly is written exactly once.
fn map_passage(row: &turso::Row) -> Result<core::models::Passage, AppError> {
    let text_raw: String = row.get(7).map_err(upstream)?;
    let inline_raw: String = row.get(8).map_err(upstream)?;
    Ok(core::models::Passage {
        id: row.get(0).map_err(upstream)?,
        exam: row.get(1).map_err(upstream)?,
        subject: row.get(2).map_err(upstream)?,
        year: req_u16(row.get_value(3).map_err(upstream)?, "passage.year")?,
        kind: row.get(4).map_err(upstream)?,
        title: opt_string(row.get_value(5).map_err(upstream)?)?,
        author: opt_string(row.get_value(6).map_err(upstream)?)?,
        text: core::models::RichText {
            text: text_raw,
            inline: json_col(&inline_raw, "passage.inline")?,
        },
    })
}

/// Map one novel row. Shared by list and detail so the twelve columns
/// are spelled exactly once.
fn map_novel(row: &turso::Row) -> Result<core::models::Novel, AppError> {
    let ypres_raw: String = row.get(5).map_err(upstream)?;
    Ok(core::models::Novel {
        id: row.get(0).map_err(upstream)?,
        title: row.get(1).map_err(upstream)?,
        author: row.get(2).map_err(upstream)?,
        year_published: opt_u16(row.get_value(3).map_err(upstream)?)?,
        exam: row.get(4).map_err(upstream)?,
        year_prescribed: json_col::<Vec<u16>>(&ypres_raw, "novel.year_prescribed")?,
        category: row.get(6).map_err(upstream)?,
        featured: {
            let f: i64 = row.get(7).map_err(upstream)?;
            if f != 0 && f != 1 {
                return Err(AppError::Upstream("novel.featured not 0/1".to_string()));
            }
            f == 1
        },
        synopsis: row.get(8).map_err(upstream)?,
        setting_place: row.get(9).map_err(upstream)?,
        setting_period: row.get(10).map_err(upstream)?,
        cover_image: opt_string(row.get_value(11).map_err(upstream)?)?,
    })
}

/// All novels, newest prescription first, then title — the established
/// order consumers already page through. Filters apply in Rust over the
/// full set: the table is a handful of rows, and pushing the JSON
/// `year_prescribed` predicate into SQL buys nothing.
pub async fn list_novels(
    s: &DbState,
    exam: Option<&str>,
    year: Option<u16>,
    featured: Option<bool>,
    category: Option<&str>,
) -> Result<Vec<core::models::Novel>, AppError> {
    let exam = exam.map(str::to_string);
    let category = category.map(str::to_string);
    with_conn(s, |conn| {
        let exam = exam.clone();
        let category = category.clone();
        async move {
        let mut rows = conn
            .query(
                "SELECT id,title,author,year_published,exam,year_prescribed,category,featured,synopsis,setting_place,setting_period,cover_image FROM novels",
                (),
            )
            .await
            .map_err(upstream)?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().await.map_err(upstream)? {
            let n = map_novel(&row)?;
            if exam.as_deref().is_some_and(|e| n.exam != e) {
                continue;
            }
            if year.is_some_and(|y| !n.year_prescribed.contains(&y)) {
                continue;
            }
            if featured.is_some_and(|f| n.featured != f) {
                continue;
            }
            if category.as_deref().is_some_and(|c| n.category != c) {
                continue;
            }
            out.push(n);
        }
        out.sort_by(|a, b| {
            b.year_prescribed
                .cmp(&a.year_prescribed)
                .then_with(|| a.title.cmp(&b.title))
        });
        Ok(out)
        }
    })
    .await
}

fn map_novel_question(row: &turso::Row) -> Result<core::models::NovelQuestion, AppError> {
    let text_raw: String = row.get(2).map_err(upstream)?;
    let inline_raw: String = row.get(3).map_err(upstream)?;
    let options_raw: String = row.get(4).map_err(upstream)?;
    Ok(core::models::NovelQuestion {
        id: row.get(0).map_err(upstream)?,
        chapter_number: opt_u8(row.get_value(1).map_err(upstream)?)?,
        text: core::models::RichText {
            text: text_raw,
            inline: json_col(&inline_raw, "novel_question.inline")?,
        },
        options: json_col(&options_raw, "novel_question.options")?,
        answer: row.get(5).map_err(upstream)?,
        explanation: match row.get_value(6).map_err(upstream)? {
            turso::Value::Null => None,
            turso::Value::Text(x) => Some(json_col(&x, "novel_question.explanation")?),
            _ => {
                return Err(AppError::Upstream(
                    "novel_question.explanation is not text".to_string(),
                ))
            }
        },
        verified: req_bool(
            row.get_value(7).map_err(upstream)?,
            "novel_question.verified",
        )?,
    })
}

/// One novel with everything: book plus chapters, characters, themes.
/// Five queries, same shape as the established detail — including quiz
/// rows with answers, which callers already read here.
pub async fn get_novel_doc(
    s: &DbState,
    id: &str,
) -> Result<Option<core::models::NovelDoc>, AppError> {
    let id = id.to_string();
    with_conn(s, |conn| {
        let id = id.clone();
        async move {
            let mut stmt = conn
            .prepare("SELECT id,title,author,year_published,exam,year_prescribed,category,featured,synopsis,setting_place,setting_period,cover_image FROM novels WHERE id=?1")
            .await
            .map_err(upstream)?;
            let mut rows = stmt
                .query([id.as_str()])
                .await
                .map_err(upstream)?;
            let Some(row) = rows.next().await.map_err(upstream)? else {
                return Ok(None);
            };
            let novel = map_novel(&row)?;
            let mut chapters = Vec::new();
            let mut rows = conn
                .query(
                    "SELECT number,title,summary,key_events FROM novel_chapters WHERE novel_id=?1 ORDER BY number",
                    [id.as_str()],
                )
                .await
                .map_err(upstream)?;
            while let Some(row) = rows.next().await.map_err(upstream)? {
                let summary_raw: Option<String> =
                    opt_string(row.get_value(2).map_err(upstream)?)?;
                let ke_raw: String = row.get(3).map_err(upstream)?;
                chapters.push(core::models::NovelChapter {
                    number: req_u8(row.get_value(0).map_err(upstream)?, "chapter.number")?,
                    title: row.get(1).map_err(upstream)?,
                    summary: summary_raw,
                    key_events: json_col(&ke_raw, "chapter.key_events")?,
                });
            }
            let mut characters = Vec::new();
            let mut rows = conn
                .query(
                    "SELECT name,role,character_type,description FROM novel_characters WHERE novel_id=?1 ORDER BY name",
                    [id.as_str()],
                )
                .await
                .map_err(upstream)?;
            while let Some(row) = rows.next().await.map_err(upstream)? {
                characters.push(core::models::NovelCharacter {
                    name: row.get(0).map_err(upstream)?,
                    role: row.get(1).map_err(upstream)?,
                    character_type: row.get(2).map_err(upstream)?,
                    description: row.get(3).map_err(upstream)?,
                });
            }
            let mut themes = Vec::new();
            let mut rows = conn
                .query(
                    "SELECT name,description,evidence FROM novel_themes WHERE novel_id=?1 ORDER BY name",
                    [id.as_str()],
                )
                .await
                .map_err(upstream)?;
            while let Some(row) = rows.next().await.map_err(upstream)? {
                let ev_raw: String = row.get(2).map_err(upstream)?;
                themes.push(core::models::NovelTheme {
                    name: row.get(0).map_err(upstream)?,
                    description: row.get(1).map_err(upstream)?,
                    evidence: json_col(&ev_raw, "novel_theme.evidence")?,
                });
            }
            let questions = list_novel_questions_inner(&conn, &id).await?;
            Ok(Some(core::models::NovelDoc {
                novel,
                chapters,
                characters,
                themes,
                questions,
            }))
        }
    })
    .await
}

async fn list_novel_questions_inner(
    conn: &turso::Connection,
    id: &str,
) -> Result<Vec<core::models::NovelQuestion>, AppError> {
    let mut out = Vec::new();
    let sql = format!(
        "SELECT id,chapter_number,text,inline,options,answer,explanation, ({}) AS verified FROM novel_questions WHERE novel_id=?1 ORDER BY id",
        verified_predicate("novel_questions")
    );
    let mut rows = conn.query(&sql, [id]).await.map_err(upstream)?;
    while let Some(row) = rows.next().await.map_err(upstream)? {
        out.push(map_novel_question(&row)?);
    }
    Ok(out)
}

/// Quiz rows for one novel in id order. No paging in SQL: a book's
/// questions are bounded by its chapters, and the handler pages the
/// filtered set with the shared `page_bounds` rule.
pub async fn list_novel_questions(
    s: &DbState,
    id: &str,
    chapter: Option<u8>,
) -> Result<Vec<core::models::NovelQuestion>, AppError> {
    let id = id.to_string();
    with_conn(s, |conn| {
        let id = id.clone();
        async move {
            let mut out = list_novel_questions_inner(&conn, &id).await?;
            if let Some(ch) = chapter {
                out.retain(|q| q.chapter_number == Some(ch));
            }
            Ok(out)
        }
    })
    .await
}

/// One passage by id. `None` when absent — the handler, not the
/// store, decides that means 404.
pub async fn get_passage(s: &DbState, id: &str) -> Result<Option<core::models::Passage>, AppError> {
    let id = id.to_string();
    with_conn(s, |conn| {
        let id = id.clone();
        async move {
            let mut stmt = conn
            .prepare("SELECT id,exam,subject,year,kind,title,author,text,inline FROM passages WHERE id=?1")
            .await
            .map_err(upstream)?;
            let mut rows = stmt
                .query([id.as_str()])
                .await
                .map_err(upstream)?;
            let Some(row) = rows.next().await.map_err(upstream)? else {
                return Ok(None);
            };
            Ok(Some(map_passage(&row)?))
        }
    })
    .await
}

/// One question by id. `None` when absent — the handler, not the
/// store, decides that means 404.
pub async fn get_question(
    s: &DbState,
    id: &str,
) -> Result<Option<core::models::Question>, AppError> {
    let id = id.to_string();
    with_conn(s, |conn| {
        let id = id.clone();
        async move {
            let sql = format!(
                "SELECT id,exam,subject,year,source,text,inline,options,answer,subtopic_id,section,passage_id,explanation,marks,difficulty, ({}) AS verified FROM questions WHERE id=?1",
                verified_predicate("questions")
            );
            let mut stmt = conn.prepare(&sql).await.map_err(upstream)?;
            let mut rows = stmt
                .query([id.as_str()])
                .await
                .map_err(upstream)?;
            let Some(row) = rows.next().await.map_err(upstream)? else {
                return Ok(None);
            };
            Ok(Some(map_question(&row)?))
        }
    })
    .await
}

fn req_u32(v: turso::Value, col: &'static str) -> Result<u32, AppError> {
    match v {
        turso::Value::Integer(n) => Ok(n as u32),
        _ => Err(AppError::Upstream(format!("{col} is not an integer"))),
    }
}

/// One topic by identity. `None` when absent — the handler, not the
/// store, decides that means 404.
pub async fn get_topic(
    s: &DbState,
    exam: &str,
    subject: &str,
    slug: &str,
) -> Result<Option<core::models::Topic>, AppError> {
    let exam = exam.to_string();
    let subject = subject.to_string();
    let slug = slug.to_string();
    with_conn(s, |conn| {
        let exam = exam.clone();
        let subject = subject.clone();
        let slug = slug.clone();
        async move {
            let mut stmt = conn
            .prepare("SELECT slug,subject,exam,name,\"order\",weight,objectives FROM topics WHERE exam=?1 AND subject=?2 AND slug=?3")
            .await
            .map_err(upstream)?;
            let mut rows = stmt
                .query([exam.as_str(), subject.as_str(), slug.as_str()])
                .await
                .map_err(upstream)?;
            let Some(row) = rows.next().await.map_err(upstream)? else {
                return Ok(None);
            };
            let objectives_raw: String = row.get(6).map_err(upstream)?;
            Ok(Some(core::models::Topic {
                slug: row.get(0).map_err(upstream)?,
                subject: row.get(1).map_err(upstream)?,
                exam: row.get(2).map_err(upstream)?,
                name: row.get(3).map_err(upstream)?,
                order: req_u32(row.get_value(4).map_err(upstream)?, "topic.order")?,
                weight: req_u32(row.get_value(5).map_err(upstream)?, "topic.weight")?,
                objectives: json_list(&objectives_raw, "topic.objectives")?,
            }))
        }
    })
    .await
}

/// Does a reportable target exist? One arm per kind, so adding a kind
/// is one line here plus one in `core::reports::parse_target_type`.
/// Reuses the readers rather than a parallel existence query: a report
/// is rare (capped per day), so paying for a full row is not worth a
/// second mapping to keep in sync.
pub async fn target_exists(
    s: &DbState,
    target_type: &str,
    target_id: &str,
) -> Result<bool, AppError> {
    match target_type {
        "question" => Ok(get_question(s, target_id).await?.is_some()),
        "passage" => Ok(get_passage(s, target_id).await?.is_some()),
        "novel" => Ok(get_novel_doc(s, target_id).await?.is_some()),
        // A topic's identity is (exam, subject, slug) — a single id
        // cannot address it, so the target id is the slash-joined triple.
        "topic" => {
            let mut parts = target_id.splitn(3, '/');
            match (parts.next(), parts.next(), parts.next()) {
                (Some(exam), Some(subject), Some(slug))
                    if !exam.is_empty() && !subject.is_empty() && !slug.is_empty() =>
                {
                    Ok(get_topic(s, exam, subject, slug).await?.is_some())
                }
                _ => Err(AppError::BadRequest(
                    "topic target_id must be exam/subject/slug".to_string(),
                )),
            }
        }
        other => Err(AppError::BadRequest(format!(
            "unknown target_type '{other}'"
        ))),
    }
}

/// One row → one `Subject`. `is_compulsory` arrives as 0/1 and anything
/// else fails loudly — a boolean column holding a 2 is corruption, not a
/// false.
fn map_subject(row: &turso::Row) -> Result<core::models::Subject, AppError> {
    let compulsory: i64 = row.get(3).map_err(upstream)?;
    if compulsory != 0 && compulsory != 1 {
        return Err(AppError::Upstream(
            "subject.is_compulsory not 0/1".to_string(),
        ));
    }
    Ok(core::models::Subject {
        slug: row.get(0).map_err(upstream)?,
        exam: row.get(1).map_err(upstream)?,
        name: row.get(2).map_err(upstream)?,
        is_compulsory: compulsory == 1,
        objective_paper_questions: opt_u32(row.get_value(4).map_err(upstream)?)?,
    })
}

/// Subjects of one exam, in stored order.
pub async fn list_subjects(
    s: &DbState,
    exam: &str,
) -> Result<Vec<core::models::Subject>, AppError> {
    let exam = exam.to_string();
    with_conn(s, |conn| {
        let exam = exam.clone();
        async move {
            let mut stmt = conn
                .prepare("SELECT slug,exam,name,is_compulsory,objective_paper_questions FROM subjects WHERE exam=?1")
                .await
                .map_err(upstream)?;
            let mut rows = stmt.query([exam.as_str()]).await.map_err(upstream)?;
            let mut out = Vec::new();
            while let Some(row) = rows.next().await.map_err(upstream)? {
                out.push(map_subject(&row)?);
            }
            Ok(out)
        }
    })
    .await
}

/// One subject of one exam. `None` when absent — the handler decides that
/// means 404.
pub async fn get_subject(
    s: &DbState,
    exam: &str,
    slug: &str,
) -> Result<Option<core::models::Subject>, AppError> {
    let exam = exam.to_string();
    let slug = slug.to_string();
    with_conn(s, |conn| {
        let exam = exam.clone();
        let slug = slug.clone();
        async move {
            let mut stmt = conn
                .prepare("SELECT slug,exam,name,is_compulsory,objective_paper_questions FROM subjects WHERE exam=?1 AND slug=?2")
                .await
                .map_err(upstream)?;
            let mut rows = stmt
                .query([exam.as_str(), slug.as_str()])
                .await
                .map_err(upstream)?;
            match rows.next().await.map_err(upstream)? {
                Some(row) => Ok(Some(map_subject(&row)?)),
                None => Ok(None),
            }
        }
    })
    .await
}

/// One row → one `Exam`. `countries`/`rules` arrive as JSON strings and
/// fail loudly here when malformed — never silently emptied.
fn map_exam(row: &turso::Row) -> Result<core::models::Exam, AppError> {
    let countries_raw: String = row.get(2).map_err(upstream)?;
    let rules_raw: String = row.get(7).map_err(upstream)?;
    Ok(core::models::Exam {
        code: row.get(0).map_err(upstream)?,
        name: row.get(1).map_err(upstream)?,
        countries: json_list(&countries_raw, "exam.countries")?,
        status: row.get(3).map_err(upstream)?,
        has_full_paper: opt_bool(row.get_value(4).map_err(upstream)?)?,
        subjects_required: opt_u32(row.get_value(5).map_err(upstream)?)?,
        duration_minutes: opt_u32(row.get_value(6).map_err(upstream)?)?,
        rules: json_list(&rules_raw, "exam.rules")?,
    })
}

/// All exams as stored.
pub async fn list_exams(s: &DbState) -> Result<Vec<core::models::Exam>, AppError> {
    with_conn(s, |conn| async move {
        let mut rows = conn
            .query(
                "SELECT code,name,countries,status,has_full_paper,subjects_required,duration_minutes,rules FROM exams",
                (),
            )
            .await
            .map_err(upstream)?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().await.map_err(upstream)? {
            out.push(map_exam(&row)?);
        }
        Ok(out)
    })
    .await
}

/// One exam by code. `None` when absent — the handler decides that is 404.
pub async fn get_exam(s: &DbState, code: &str) -> Result<Option<core::models::Exam>, AppError> {
    let code = code.to_string();
    with_conn(s, |conn| {
        let code = code.clone();
        async move {
            let mut stmt = conn
                .prepare("SELECT code,name,countries,status,has_full_paper,subjects_required,duration_minutes,rules FROM exams WHERE code=?1")
                .await
                .map_err(upstream)?;
            let mut rows = stmt.query([code.as_str()]).await.map_err(upstream)?;
            match rows.next().await.map_err(upstream)? {
                Some(row) => Ok(Some(map_exam(&row)?)),
                None => Ok(None),
            }
        }
    })
    .await
}

/// The board's paper requirements for one exam in one country. Empty where
/// the shape is unstated — an unstated paper is never complete.
pub async fn list_requirements(
    s: &DbState,
    exam: &str,
    country: &str,
) -> Result<Vec<core::models::Requirement>, AppError> {
    let exam = exam.to_string();
    let country = country.to_string();
    with_conn(s, |conn| {
        let exam = exam.clone();
        let country = country.clone();
        async move {
            let mut stmt = conn
                .prepare("SELECT \"group\",min_select,subjects FROM exam_requirements WHERE exam=?1 AND country=?2 ORDER BY \"group\"")
                .await
                .map_err(upstream)?;
            let mut rows = stmt
                .query([exam.as_str(), country.as_str()])
                .await
                .map_err(upstream)?;
            let mut out = Vec::new();
            while let Some(row) = rows.next().await.map_err(upstream)? {
                let subjects_raw: String = row.get(2).map_err(upstream)?;
                out.push(core::models::Requirement {
                    group: row.get(0).map_err(upstream)?,
                    min_select: req_u32(
                        row.get_value(1).map_err(upstream)?,
                        "requirement.min_select",
                    )?,
                    subjects: json_list(&subjects_raw, "requirement.subjects")?,
                });
            }
            Ok(out)
        }
    })
    .await
}

/// One query for every subject's figures under an exam: rows held, rows
/// verified (the same D62 rule every reader uses), and the marks spread. A
/// scheme is derived from this rather than N per-subject round trips.
pub async fn subject_stats(
    s: &DbState,
    exam: &str,
    country: Option<&str>,
) -> Result<std::collections::HashMap<String, core::papers::SubjectStat>, AppError> {
    let exam = exam.to_string();
    let country = country.map(str::to_string);
    with_conn(s, |conn| {
        let exam = exam.clone();
        let country = country.clone();
        async move {
            let sql = format!(
                "SELECT subject,COUNT(*),SUM(CASE WHEN {} THEN 1 ELSE 0 END),COUNT(DISTINCT marks),MIN(marks) FROM questions WHERE exam=?1 AND {} GROUP BY subject",
                verified_predicate("questions"),
                scope_predicate(2)
            );
            let mut stmt = conn.prepare(&sql).await.map_err(upstream)?;
            let params = [turso::Value::Text(exam), scope_param(&country)];
            let mut rows = stmt.query(params).await.map_err(upstream)?;
            let mut out = std::collections::HashMap::new();
            while let Some(row) = rows.next().await.map_err(upstream)? {
                let subject: String = row.get(0).map_err(upstream)?;
                out.insert(
                    subject,
                    core::papers::SubjectStat {
                        held: req_u32(row.get_value(1).map_err(upstream)?, "stats.held")?,
                        verified: req_u32(
                            row.get_value(2).map_err(upstream)?,
                            "stats.verified",
                        )?,
                        distinct_marks: req_u32(
                            row.get_value(3).map_err(upstream)?,
                            "stats.distinct_marks",
                        )?,
                        marks_low: req_f32(row.get_value(4).map_err(upstream)?, "stats.marks_low")?,
                    },
                );
            }
            Ok(out)
        }
    })
    .await
}

/// Every row one subject holds, in id order, `verified` derived. No paging:
/// assembly and readiness need the whole pool, and a paged read would
/// silently under-count a subject that outgrows one page.
pub async fn subject_rows(
    s: &DbState,
    exam: &str,
    subject: &str,
    country: Option<&str>,
) -> Result<Vec<core::models::Question>, AppError> {
    let exam = exam.to_string();
    let subject = subject.to_string();
    let country = country.map(str::to_string);
    with_conn(s, |conn| {
        let exam = exam.clone();
        let subject = subject.clone();
        let country = country.clone();
        async move {
            let sql = format!(
                "SELECT id,exam,subject,year,source,text,inline,options,answer,subtopic_id,section,passage_id,explanation,marks,difficulty,({}) AS verified FROM questions WHERE exam=?1 AND subject=?2 AND {} ORDER BY id",
                verified_predicate("questions"),
                scope_predicate(3)
            );
            let mut stmt = conn.prepare(&sql).await.map_err(upstream)?;
            let params = [
                turso::Value::Text(exam),
                turso::Value::Text(subject),
                scope_param(&country),
            ];
            let mut rows = stmt.query(params).await.map_err(upstream)?;
            let mut out = Vec::new();
            while let Some(row) = rows.next().await.map_err(upstream)? {
                out.push(map_question(&row)?);
            }
            Ok(out)
        }
    })
    .await
}

/// One subject's syllabus: topics in `order` with their subtopic slugs.
/// This is the tree that attributes questions to topics; a topic the bank
/// does not state is never invented.
pub async fn list_syllabus(
    s: &DbState,
    exam: &str,
    subject: &str,
) -> Result<Vec<core::papers::SyllabusTopic>, AppError> {
    let exam = exam.to_string();
    let subject = subject.to_string();
    with_conn(s, |conn| {
        let exam = exam.clone();
        let subject = subject.clone();
        async move {
            let mut stmt = conn
                .prepare("SELECT t.slug,t.name,COALESCE(st.slug,'') FROM topics t LEFT JOIN subtopics st ON st.topic=t.slug WHERE t.exam=?1 AND t.subject=?2 ORDER BY t.\"order\",t.slug,st.\"order\",st.slug")
                .await
                .map_err(upstream)?;
            let mut rows = stmt
                .query([exam.as_str(), subject.as_str()])
                .await
                .map_err(upstream)?;
            let mut out: Vec<core::papers::SyllabusTopic> = Vec::new();
            while let Some(row) = rows.next().await.map_err(upstream)? {
                let slug: String = row.get(0).map_err(upstream)?;
                let name: String = row.get(1).map_err(upstream)?;
                let sub: String = row.get(2).map_err(upstream)?;
                match out.last_mut() {
                    Some(t) if t.slug == slug => {
                        if !sub.is_empty() {
                            t.subtopics.push(sub);
                        }
                    }
                    _ => out.push(core::papers::SyllabusTopic {
                        slug,
                        name,
                        subtopics: if sub.is_empty() { Vec::new() } else { vec![sub] },
                    }),
                }
            }
            Ok(out)
        }
    })
    .await
}

/// Dump up to `limit` rows of one table. The table must be on the `core`
/// allowlist: `SELECT *` bypasses every withholding rule, so a credential
/// table or an answer-bearing one must be unreachable here, not merely
/// hidden from the listing. Anything else answers 404 so the surface cannot
/// be used to probe for table names.
pub async fn fetch_rows(
    s: &DbState,
    table: &str,
    limit: u64,
) -> Result<crate::core::models::RowPage, AppError> {
    if !core::validate::ident(table) || !core::catalog::is_introspectable(table) {
        return Err(AppError::NotFound);
    }
    let limit = limit.clamp(1, 100);
    let table = table.to_string();
    with_conn(s, |conn| {
        let table = table.clone();
        async move {
            let sql = format!("SELECT * FROM \"{table}\" LIMIT {limit}");
            let mut rows = conn.query(&sql, ()).await.map_err(upstream)?;
            let mut out: Vec<Vec<String>> = Vec::new();
            let mut width = 0;
            while let Some(row) = rows.next().await.map_err(upstream)? {
                width = row.column_count();
                let mut r = Vec::with_capacity(width);
                for i in 0..width {
                    let v = row.get_value(i).map_err(upstream)?;
                    r.push(match v {
                        turso::Value::Null => String::from("null"),
                        turso::Value::Text(t) => t,
                        turso::Value::Integer(n) => n.to_string(),
                        turso::Value::Real(f) => f.to_string(),
                        turso::Value::Blob(b) => format!("<{} bytes>", b.len()),
                    });
                }
                out.push(r);
            }
            Ok(crate::core::models::RowPage {
                cols: (0..width).map(|i| format!("c{i}")).collect(),
                rows: out,
            })
        }
    })
    .await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicU64;

    static TEST_DB_SEQ: AtomicU64 = AtomicU64::new(0);

    async fn local_exams_db() -> crate::store::SyncDb {
        let n = TEST_DB_SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("utmelab-exams-test-{}-{n}.db", std::process::id()));
        // Fully offline: bootstrap_if_empty(false) keeps build() from
        // issuing any HTTP, and tests never pull — connect/execute/query
        // all run against the local file.
        let db = turso::sync::Builder::new_remote(path.to_str().expect("tmp path"))
            .with_remote_url("http://127.0.0.1:9")
            .with_auth_token("test-only")
            .bootstrap_if_empty(false)
            .build()
            .await
            .expect("local sync db builds offline");
        let conn = db.connect().await.expect("connect");
        conn.execute(
            "CREATE TABLE exams (code TEXT, name TEXT, countries TEXT, status TEXT, has_full_paper INTEGER, subjects_required INTEGER, duration_minutes INTEGER, rules TEXT)",
            (),
        )
        .await
        .expect("create exams");
        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','Joint Admissions','[\"NG\"]','live',1,4,120,'[\"r1\"]')",
            (),
        )
        .await
        .expect("insert jamb");
        conn.execute(
            "INSERT INTO exams VALUES ('WAEC','West African','[]','planned',NULL,NULL,NULL,'[]')",
            (),
        )
        .await
        .expect("insert waec");
        conn.execute(
            "CREATE TABLE exam_requirements (exam TEXT, country TEXT, \"group\" TEXT, min_select INTEGER, subjects TEXT)",
            (),
        )
        .await
        .expect("create requirements");
        conn.execute(
            "INSERT INTO exam_requirements VALUES ('JAMB','NG','core',1,'[\"use-of-english\"]')",
            (),
        )
        .await
        .expect("insert core requirement");
        conn.execute(
            "INSERT INTO exam_requirements VALUES ('JAMB','NG','elective',3,'[]')",
            (),
        )
        .await
        .expect("insert elective requirement");
        conn.execute(
            "CREATE TABLE subjects (slug TEXT, exam TEXT, name TEXT, is_compulsory INTEGER, objective_paper_questions INTEGER)",
            (),
        )
        .await
        .expect("create subjects");
        conn.execute(
            "INSERT INTO subjects VALUES ('use-of-english','JAMB','Use of English',1,50)",
            (),
        )
        .await
        .expect("insert english");
        conn.execute(
            "INSERT INTO subjects VALUES ('physics','JAMB','Physics',0,NULL)",
            (),
        )
        .await
        .expect("insert physics");
        conn.execute(
            "INSERT INTO subjects VALUES ('english-language','WAEC','English Language',1,60)",
            (),
        )
        .await
        .expect("insert waec english");
        conn.execute(
            "CREATE TABLE topics (slug TEXT, subject TEXT, exam TEXT, name TEXT, \"order\" INTEGER, weight INTEGER, objectives TEXT)",
            (),
        )
        .await
        .expect("create topics");
        conn.execute(
            "INSERT INTO topics VALUES ('algebra','mathematics','JAMB','Algebra',3,15,'[\"solve\"]')",
            (),
        )
        .await
        .expect("insert algebra");
        conn.execute(
            "INSERT INTO topics VALUES ('geometry','mathematics','JAMB','Geometry',4,0,'[]')",
            (),
        )
        .await
        .expect("insert geometry");
        conn.execute(
            "CREATE TABLE subtopics (slug TEXT, topic TEXT, name TEXT, \"order\" INTEGER, objectives TEXT)",
            (),
        )
        .await
        .expect("create subtopics");
        conn.execute(
            "INSERT INTO subtopics VALUES ('geometry-basics','geometry','Geometry basics',1,'[]')",
            (),
        )
        .await
        .expect("insert subtopic");
        conn.execute(
            "CREATE TABLE topic_countries (topic TEXT NOT NULL, country TEXT NOT NULL, PRIMARY KEY (topic, country))",
            (),
        )
        .await
        .expect("create topic_countries");
        conn.execute(
            "CREATE TABLE questions (id TEXT, exam TEXT, subject TEXT, year INTEGER, source TEXT, text TEXT, inline TEXT, options TEXT, answer TEXT, subtopic_id TEXT, section TEXT, passage_id TEXT, explanation TEXT, marks REAL, difficulty INTEGER, content_hash TEXT)",
            (),
        )
        .await
        .expect("create questions");
        conn.execute(
            "INSERT INTO questions VALUES ('q1','JAMB','physics',2025,'past_paper','What is 2+2?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"4\",\"inline\":[]}}]','a',NULL,NULL,NULL,'{\"key_point\":{\"text\":\"addition\",\"inline\":[]},\"body\":{\"text\":\"2+2=4\",\"inline\":[]}}',1.0,2,'h1')",
            (),
        )
        .await
        .expect("insert q1");
        conn.execute(
            "CREATE TABLE reports (id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL, reporter TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT, created_at INTEGER NOT NULL, UNIQUE(reporter, target_type, target_id, reason))",
            (),
        )
        .await
        .expect("create reports");
        conn.execute(
            "CREATE TABLE verifications (id TEXT, question_id TEXT, kind TEXT, verdict TEXT, scope TEXT, verifier TEXT, detail TEXT, content_hash TEXT, created_at TEXT)",
            (),
        )
        .await
        .expect("create verifications");
        // q1: a human pass matching its content hash → verified.
        conn.execute(
            "INSERT INTO verifications VALUES ('v1','q1','human','pass','[\"answer\",\"explanation\"]','review',NULL,'h1','2026-01-01T00:00:00Z')",
            (),
        )
        .await
        .expect("insert v1");
        // q3: a human pass against a *stale* hash → an edit voids it.
        conn.execute(
            "INSERT INTO verifications VALUES ('v2','q3','human','pass','[\"answer\",\"explanation\"]','review',NULL,'wrong','2026-01-01T00:00:00Z')",
            (),
        )
        .await
        .expect("insert v2");
        conn.execute(
            "CREATE TABLE novels (id TEXT, title TEXT, author TEXT, year_published INTEGER, exam TEXT, year_prescribed TEXT, category TEXT, featured INTEGER, synopsis TEXT, setting_place TEXT, setting_period TEXT, cover_image TEXT)",
            (),
        )
        .await
        .expect("create novels");
        conn.execute(
            "INSERT INTO novels VALUES ('lekki','The Lekki Headmaster','A',2020,'JAMB','[2025,2026]','english',1,'syn','Lagos','modern',NULL)",
            (),
        )
        .await
        .expect("insert lekki");
        conn.execute(
            "INSERT INTO novels VALUES ('old','Old Book','B',NULL,'WAEC','[2024]','literature',0,'syn','Accra','past',NULL)",
            (),
        )
        .await
        .expect("insert old");
        conn.execute(
            "CREATE TABLE novel_chapters (novel_id TEXT, number INTEGER, title TEXT, summary TEXT, key_events TEXT)",
            (),
        )
        .await
        .expect("create chapters");
        conn.execute(
            "INSERT INTO novel_chapters VALUES ('lekki',1,'Arrival',NULL,'[\"bus\"]')",
            (),
        )
        .await
        .expect("insert chapter");
        conn.execute(
            "CREATE TABLE novel_characters (novel_id TEXT, name TEXT, role TEXT, character_type TEXT, description TEXT)",
            (),
        )
        .await
        .expect("create characters");
        conn.execute(
            "INSERT INTO novel_characters VALUES ('lekki','Ada','hero','heroine','brave')",
            (),
        )
        .await
        .expect("insert character");
        conn.execute(
            "CREATE TABLE novel_themes (novel_id TEXT, name TEXT, description TEXT, evidence TEXT)",
            (),
        )
        .await
        .expect("create themes");
        conn.execute(
            "INSERT INTO novel_themes VALUES ('lekki','Hope','endures','[\"dawn\"]')",
            (),
        )
        .await
        .expect("insert theme");
        conn.execute(
            "CREATE TABLE novel_questions (id TEXT, novel_id TEXT, chapter_number INTEGER, text TEXT, inline TEXT, options TEXT, answer TEXT, explanation TEXT, content_hash TEXT)",
            (),
        )
        .await
        .expect("create novel_questions");
        conn.execute(
            "INSERT INTO novel_questions VALUES ('nq1','lekki',1,'Who?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"Ada\",\"inline\":[]}}]','a',NULL,'nh1')",
            (),
        )
        .await
        .expect("insert nq1");
        conn.execute(
            "INSERT INTO novel_questions VALUES ('nq2','lekki',2,'Where?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"Lagos\",\"inline\":[]}}]','a',NULL,'nh2')",
            (),
        )
        .await
        .expect("insert nq2");
        // nq1 is verified; nq2 is not — the novel side of the same rule.
        conn.execute(
            "INSERT INTO verifications VALUES ('v3','nq1','human','pass','[\"answer\",\"explanation\"]','review',NULL,'nh1','2026-01-01T00:00:00Z')",
            (),
        )
        .await
        .expect("insert novel verification");
        conn.execute(
            "CREATE TABLE passages (id TEXT, exam TEXT, subject TEXT, year INTEGER, kind TEXT, title TEXT, author TEXT, text TEXT, inline TEXT)",
            (),
        )
        .await
        .expect("create passages");
        conn.execute(
            "INSERT INTO passages VALUES ('p1','JAMB','english',2025,'comprehension','The Market',NULL,'A market sells things.','[]')",
            (),
        )
        .await
        .expect("insert p1");
        conn.execute(
            "INSERT INTO questions VALUES ('q2','JAMB','physics',2024,'authored','What is 3+3?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"6\",\"inline\":[]}}]','a','algebra',NULL,NULL,NULL,2.0,3,'h2')",
            (),
        )
        .await
        .expect("insert q2");
        conn.execute(
            "INSERT INTO questions VALUES ('q3','WAEC','physics',2025,'past_paper','What is 50% of 10?','[]','[{\"id\":\"a\",\"text\":{\"text\":\"5\",\"inline\":[]}}]','a',NULL,NULL,NULL,NULL,1.0,1,'h3')",
            (),
        )
        .await
        .expect("insert q3");
        std::sync::Arc::new(db)
    }

    #[tokio::test]
    async fn list_exams_maps_all_columns() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let exams = list_exams(&s).await.expect("list exams");
        assert_eq!(exams.len(), 2);
        let jamb = exams.iter().find(|e| e.code == "JAMB").expect("jamb row");
        assert_eq!(jamb.name, "Joint Admissions");
        assert_eq!(jamb.countries, vec!["NG".to_string()]);
        assert_eq!(jamb.status, "live");
        assert_eq!(jamb.has_full_paper, Some(true));
        assert_eq!(jamb.subjects_required, Some(4));
        assert_eq!(jamb.duration_minutes, Some(120));
        assert_eq!(jamb.rules, vec!["r1".to_string()]);
        let waec = exams.iter().find(|e| e.code == "WAEC").expect("waec row");
        assert_eq!(waec.has_full_paper, None);
        assert_eq!(waec.subjects_required, None);
        assert_eq!(waec.duration_minutes, None);
        assert!(waec.countries.is_empty());
        assert!(waec.rules.is_empty());
    }

    #[tokio::test]
    async fn list_exams_rejects_malformed_json() {
        let db = local_exams_db().await;
        db.connect()
            .await
            .expect("connect")
            .execute(
                "INSERT INTO exams VALUES ('BAD','Bad','not-json','live',NULL,NULL,NULL,'[]')",
                (),
            )
            .await
            .expect("insert bad row");
        let s = crate::state::DbState::detached(db);
        let err = list_exams(&s)
            .await
            .expect_err("malformed json fails loudly");
        assert!(matches!(err, crate::error::AppError::Upstream(_)));
    }

    #[tokio::test]
    async fn list_subjects_scopes_to_exam() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let jamb = list_subjects(&s, "JAMB").await.expect("jamb subjects");
        assert_eq!(jamb.len(), 2);
        let eng = jamb
            .iter()
            .find(|x| x.slug == "use-of-english")
            .expect("english row");
        assert_eq!(eng.name, "Use of English");
        assert_eq!(eng.exam, "JAMB");
        assert!(eng.is_compulsory);
        assert_eq!(eng.objective_paper_questions, Some(50));
        let phy = jamb
            .iter()
            .find(|x| x.slug == "physics")
            .expect("physics row");
        assert!(!phy.is_compulsory);
        assert_eq!(phy.objective_paper_questions, None);
        let waec = list_subjects(&s, "WAEC").await.expect("waec subjects");
        assert_eq!(waec.len(), 1);
        assert_eq!(waec[0].slug, "english-language");
        let none = list_subjects(&s, "NECO").await.expect("unknown exam");
        assert!(none.is_empty());
    }

    #[tokio::test]
    async fn get_topic_maps_row_and_missing_is_none() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let t = get_topic(&s, "JAMB", "mathematics", "algebra")
            .await
            .expect("get topic")
            .expect("topic present");
        assert_eq!(t.slug, "algebra");
        assert_eq!(t.subject, "mathematics");
        assert_eq!(t.exam, "JAMB");
        assert_eq!(t.name, "Algebra");
        assert_eq!(t.order, 3);
        assert_eq!(t.weight, 15);
        assert_eq!(t.objectives, vec!["solve".to_string()]);
        let g = get_topic(&s, "JAMB", "mathematics", "geometry")
            .await
            .expect("get geometry")
            .expect("present");
        assert_eq!(g.weight, 0);
        assert!(g.objectives.is_empty());
        let missing = get_topic(&s, "JAMB", "mathematics", "nope")
            .await
            .expect("query succeeds");
        assert!(missing.is_none());
    }

    #[tokio::test]
    async fn get_question_maps_full_row() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let q = get_question(&s, "q1")
            .await
            .expect("get question")
            .expect("question present");
        assert_eq!(q.id, "q1");
        assert_eq!(q.exam, "JAMB");
        assert_eq!(q.subject, "physics");
        assert_eq!(q.year, 2025);
        assert_eq!(q.source, "past_paper");
        assert_eq!(q.text.text, "What is 2+2?");
        assert!(q.text.inline.is_empty());
        assert_eq!(q.options.len(), 1);
        assert_eq!(q.options[0].id, "a");
        assert_eq!(q.options[0].text.text, "4");
        assert_eq!(q.answer, "a");
        assert_eq!(q.subtopic_id, None);
        assert_eq!(q.section, None);
        assert_eq!(q.passage_id, None);
        let expl = q.explanation.expect("explanation present");
        assert_eq!(expl.body.text, "2+2=4");
        assert_eq!(expl.trap, None);
        assert_eq!(q.marks, 1.0);
        assert_eq!(q.difficulty, 2);
    }

    #[tokio::test]
    async fn list_questions_pages_and_filters() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let blank = QuestionFilter::default();
        let (p1, total) = list_questions(&s, &blank, 1, 2).await.expect("page 1");
        assert_eq!(total, 3);
        assert_eq!(p1.len(), 2);
        assert_eq!(p1[0].id, "q1");
        let (p2, total2) = list_questions(&s, &blank, 2, 2).await.expect("page 2");
        assert_eq!(total2, 3);
        assert_eq!(p2.len(), 1);
        assert_eq!(p2[0].id, "q3");

        let jamb = QuestionFilter {
            exam: Some("JAMB".to_string()),
            ..Default::default()
        };
        let (rows, total) = list_questions(&s, &jamb, 1, 50).await.expect("exam filter");
        assert_eq!(total, 2);
        assert!(rows.iter().all(|q| q.exam == "JAMB"));

        let y2024 = QuestionFilter {
            year: Some(2024),
            ..Default::default()
        };
        let (rows, total) = list_questions(&s, &y2024, 1, 50)
            .await
            .expect("year filter");
        assert_eq!(total, 1);
        assert_eq!(rows[0].id, "q2");

        let sub = QuestionFilter {
            subtopic_id: Some("algebra".to_string()),
            ..Default::default()
        };
        let (rows, total) = list_questions(&s, &sub, 1, 50)
            .await
            .expect("subtopic filter");
        assert_eq!(total, 1);
        assert_eq!(rows[0].id, "q2");

        let src = QuestionFilter {
            source: Some("authored".to_string()),
            ..Default::default()
        };
        let (_, total) = list_questions(&s, &src, 1, 50)
            .await
            .expect("source filter");
        assert_eq!(total, 1);
    }

    #[tokio::test]
    async fn list_questions_text_search_escapes_wildcards() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        // Literal % must not turn into "match everything".
        let pct = QuestionFilter {
            text: Some("50%".to_string()),
            ..Default::default()
        };
        let (rows, total) = list_questions(&s, &pct, 1, 50).await.expect("pct search");
        assert_eq!(total, 1);
        assert_eq!(rows[0].id, "q3");
        // Case-insensitive substring.
        let what = QuestionFilter {
            text: Some("what IS".to_string()),
            ..Default::default()
        };
        let (_, total) = list_questions(&s, &what, 1, 50).await.expect("case search");
        assert_eq!(total, 3);
    }

    #[tokio::test]
    async fn subject_exists_checks_identity() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        assert!(subject_exists(&s, "JAMB", "physics").await.expect("check"));
        assert!(!subject_exists(&s, "JAMB", "nope").await.expect("check"));
        assert!(!subject_exists(&s, "NECO", "physics").await.expect("check"));
    }

    #[test]
    fn like_literal_escapes() {
        assert_eq!(like_literal("50%"), "%50\\%%");
        assert_eq!(like_literal("a_b\\c"), "%a\\_b\\\\c%");
        assert_eq!(like_literal("plain"), "%plain%");
    }

    #[tokio::test]
    async fn get_question_missing_is_none() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let missing = get_question(&s, "nope").await.expect("query succeeds");
        assert!(missing.is_none());
    }

    #[tokio::test]
    async fn get_question_rejects_bad_option_json() {
        let db = local_exams_db().await;
        db.connect()
            .await
            .expect("connect")
            .execute(
                "INSERT INTO questions VALUES ('bad','JAMB','physics',2025,'past_paper','t','[]','not-json','a',NULL,NULL,NULL,NULL,1.0,1,'hbad')",
                (),
            )
            .await
            .expect("insert bad row");
        let s = crate::state::DbState::detached(db);
        let err = get_question(&s, "bad")
            .await
            .expect_err("malformed options fail loudly");
        assert!(matches!(err, crate::error::AppError::Upstream(_)));
    }

    #[tokio::test]
    async fn get_passage_maps_row_and_missing_is_none() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let p = get_passage(&s, "p1")
            .await
            .expect("get passage")
            .expect("passage present");
        assert_eq!(p.id, "p1");
        assert_eq!(p.exam, "JAMB");
        assert_eq!(p.subject, "english");
        assert_eq!(p.year, 2025);
        assert_eq!(p.kind, "comprehension");
        assert_eq!(p.title.as_deref(), Some("The Market"));
        assert_eq!(p.author, None);
        assert_eq!(p.text.text, "A market sells things.");
        assert!(p.text.inline.is_empty());
        let missing = get_passage(&s, "nope").await.expect("query succeeds");
        assert!(missing.is_none());
    }

    #[tokio::test]
    async fn get_passage_rejects_bad_inline() {
        let db = local_exams_db().await;
        db.connect()
            .await
            .expect("connect")
            .execute(
                "INSERT INTO passages VALUES ('bad','JAMB','english',2025,'comprehension',NULL,NULL,'t','nope')",
                (),
            )
            .await
            .expect("insert bad row");
        let s = crate::state::DbState::detached(db);
        let err = get_passage(&s, "bad")
            .await
            .expect_err("malformed inline fails loudly");
        assert!(matches!(err, crate::error::AppError::Upstream(_)));
    }

    #[tokio::test]
    async fn list_blueprints_maps_sparse_rows() {
        let db = local_exams_db().await;
        db.connect()
            .await
            .expect("connect")
            .execute(
                "CREATE TABLE blueprints (exam TEXT, subject TEXT, level TEXT, topic TEXT, section TEXT, members TEXT, paper_size INTEGER, pct REAL, pct_low REAL, pct_high REAL, expected REAL, expected_low REAL, expected_high REAL, source TEXT, sample TEXT, method TEXT, confidence TEXT, status TEXT, note TEXT)",
                (),
            )
            .await
            .expect("create blueprints");
        db.connect()
            .await
            .expect("connect")
            .execute(
                "INSERT INTO blueprints VALUES ('JAMB','physics','topic','algebra',NULL,'[\"a\"]',40,0.5,NULL,NULL,18.0,NULL,NULL,'past','n=200','freq','high','active','note')",
                (),
            )
            .await
            .expect("insert full row");
        db.connect()
            .await
            .expect("connect")
            .execute(
                "INSERT INTO blueprints VALUES ('JAMB','physics','paper',NULL,NULL,'[]',40,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'freq',NULL,'draft',NULL)",
                (),
            )
            .await
            .expect("insert sparse row");
        let s = crate::state::DbState::detached(db);
        let rows = list_blueprints(&s, "JAMB", "physics")
            .await
            .expect("list blueprints");
        assert_eq!(rows.len(), 2);
        let full = &rows[0];
        assert_eq!(full.level, "topic");
        assert_eq!(full.topic.as_deref(), Some("algebra"));
        assert_eq!(full.section, None);
        assert_eq!(full.members, vec!["a".to_string()]);
        assert_eq!(full.paper_size, 40);
        assert_eq!(full.pct, Some(0.5));
        assert_eq!(full.expected, Some(18.0));
        assert_eq!(full.note, "note");
        let sparse = &rows[1];
        assert_eq!(sparse.topic, None);
        assert_eq!(sparse.pct, None);
        assert!(sparse.members.is_empty());
        assert_eq!(sparse.note, "");
        let none = list_blueprints(&s, "NECO", "physics")
            .await
            .expect("unknown combo");
        assert!(none.is_empty());
    }

    #[tokio::test]
    async fn list_novels_filters_and_sorts() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let all = list_novels(&s, None, None, None, None)
            .await
            .expect("list novels");
        assert_eq!(all.len(), 2);
        // Newest prescription first, then title.
        assert_eq!(all[0].id, "lekki");
        assert_eq!(all[1].id, "old");
        assert!(all[0].featured);
        assert_eq!(all[0].year_prescribed, vec![2025, 2026]);
        assert_eq!(all[1].year_published, None);
        let feat = list_novels(&s, None, None, Some(true), None)
            .await
            .expect("featured filter");
        assert_eq!(feat.len(), 1);
        assert_eq!(feat[0].id, "lekki");
        let y2024 = list_novels(&s, None, Some(2024), None, None)
            .await
            .expect("year filter");
        assert_eq!(y2024.len(), 1);
        assert_eq!(y2024[0].id, "old");
        let lit = list_novels(&s, Some("WAEC"), None, None, Some("literature"))
            .await
            .expect("exam+category filter");
        assert_eq!(lit.len(), 1);
        let none = list_novels(&s, Some("NECO"), None, None, None)
            .await
            .expect("unknown exam");
        assert!(none.is_empty());
    }

    #[tokio::test]
    async fn get_novel_doc_assembles_children() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let doc = get_novel_doc(&s, "lekki")
            .await
            .expect("get doc")
            .expect("doc present");
        assert_eq!(doc.novel.title, "The Lekki Headmaster");
        assert_eq!(doc.chapters.len(), 1);
        assert_eq!(doc.chapters[0].number, 1);
        assert_eq!(doc.chapters[0].summary, None);
        assert_eq!(doc.chapters[0].key_events, vec!["bus".to_string()]);
        assert_eq!(doc.characters.len(), 1);
        assert_eq!(doc.characters[0].name, "Ada");
        assert_eq!(doc.themes.len(), 1);
        assert_eq!(doc.themes[0].evidence, vec!["dawn".to_string()]);
        assert_eq!(doc.questions.len(), 2);
        let missing = get_novel_doc(&s, "nope").await.expect("query succeeds");
        assert!(missing.is_none());
    }

    #[tokio::test]
    async fn list_novel_questions_filters_chapter() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let all = list_novel_questions(&s, "lekki", None)
            .await
            .expect("all questions");
        assert_eq!(all.len(), 2);
        assert_eq!(all[0].id, "nq1");
        let ch2 = list_novel_questions(&s, "lekki", Some(2))
            .await
            .expect("chapter filter");
        assert_eq!(ch2.len(), 1);
        assert_eq!(ch2[0].id, "nq2");
        assert_eq!(ch2[0].chapter_number, Some(2));
    }

    // file_report itself pushes to cloud, so it cannot run offline.
    // This pins the SQL contract it relies on: INSERT OR IGNORE is a
    // no-op on repeats, and the original id reads back for the receipt.
    #[tokio::test]
    async fn report_insert_or_ignore_is_idempotent() {
        let db = local_exams_db().await;
        let conn = db.connect().await.expect("connect");
        let first: u64 = conn
            .execute(
                "INSERT OR IGNORE INTO reports (id, target_type, target_id, reporter, reason, detail, created_at) VALUES ('r1','question','q1','k1','wrong_answer',NULL,1)",
                (),
            )
            .await
            .expect("first insert");
        assert_eq!(first, 1);
        let second: u64 = conn
            .execute(
                "INSERT OR IGNORE INTO reports (id, target_type, target_id, reporter, reason, detail, created_at) VALUES ('r2','question','q1','k1','wrong_answer',NULL,1)",
                (),
            )
            .await
            .expect("repeat insert");
        assert_eq!(second, 0);
        let mut rows = conn
            .query(
                "SELECT id FROM reports WHERE reporter='k1' AND target_type='question' AND target_id='q1' AND reason='wrong_answer'",
                (),
            )
            .await
            .expect("select back");
        let row = rows.next().await.expect("next").expect("row present");
        let id: String = row.get(0).expect("id column");
        assert_eq!(id, "r1");
    }

    #[tokio::test]
    async fn target_exists_dispatches_per_kind() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        assert!(target_exists(&s, "question", "q1").await.expect("q"));
        assert!(!target_exists(&s, "question", "nope").await.expect("q"));
        assert!(target_exists(&s, "passage", "p1").await.expect("p"));
        assert!(target_exists(&s, "novel", "lekki").await.expect("n"));
        // Topics address the slash-joined triple.
        assert!(target_exists(&s, "topic", "JAMB/mathematics/algebra")
            .await
            .expect("t"));
        assert!(!target_exists(&s, "topic", "JAMB/mathematics/missing")
            .await
            .expect("t"));
        let bad = target_exists(&s, "topic", "noslash").await;
        assert!(matches!(bad, Err(crate::error::AppError::BadRequest(_))));
        let unknown = target_exists(&s, "planet", "x").await;
        assert!(matches!(
            unknown,
            Err(crate::error::AppError::BadRequest(_))
        ));
    }

    #[tokio::test]
    async fn file_report_daily_cap_trips() {
        let db = local_exams_db().await;
        // Seed 10 filings directly: file_report itself pushes, so the
        // cap path is exercised with the count already at the limit —
        // the trip happens before any write.
        let conn = db.connect().await.expect("connect");
        for i in 0..10 {
            conn.execute(
                &format!("INSERT INTO reports VALUES ('r{i}','question','q{i}','k9','other',NULL,9999999999)"),
                (),
            )
            .await
            .expect("seed filing");
        }
        let s = crate::state::DbState::detached(db);
        let err = crate::store::accounts::file_report(&s, "k9", "question", "qX", "other", None)
            .await
            .expect_err("11th filing trips cap");
        assert!(matches!(err, crate::error::AppError::RateLimited));
    }

    #[tokio::test]
    async fn list_subjects_rejects_bad_flag() {
        let db = local_exams_db().await;
        db.connect()
            .await
            .expect("connect")
            .execute(
                "INSERT INTO subjects VALUES ('odd','JAMB','Odd',2,NULL)",
                (),
            )
            .await
            .expect("insert bad row");
        let s = crate::state::DbState::detached(db);
        let err = list_subjects(&s, "JAMB")
            .await
            .expect_err("non-0/1 flag fails loudly");
        assert!(matches!(err, crate::error::AppError::Upstream(_)));
    }

    #[tokio::test]
    async fn question_verified_derives_from_the_log() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        // q1 carries a human pass against its current content hash.
        let q1 = get_question(&s, "q1").await.expect("q1").expect("present");
        assert!(q1.verified);
        // q2 has no verification at all.
        let q2 = get_question(&s, "q2").await.expect("q2").expect("present");
        assert!(!q2.verified);
        // q3's only pass is against a stale hash, so the edit voids it.
        let q3 = get_question(&s, "q3").await.expect("q3").expect("present");
        assert!(!q3.verified);
    }

    #[tokio::test]
    async fn verified_filter_agrees_with_the_flag() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let only = QuestionFilter {
            verified: Some(true),
            ..Default::default()
        };
        let (rows, total) = list_questions(&s, &only, 1, 50)
            .await
            .expect("verified filter");
        assert_eq!(total, 1);
        assert_eq!(rows[0].id, "q1");
        assert!(rows[0].verified);
        let unverified = QuestionFilter {
            verified: Some(false),
            ..Default::default()
        };
        let (rows, total) = list_questions(&s, &unverified, 1, 50)
            .await
            .expect("unverified filter");
        assert_eq!(total, 2);
        assert!(rows.iter().all(|q| !q.verified));
    }

    #[tokio::test]
    async fn a_later_human_fail_voids_an_earlier_pass() {
        let db = local_exams_db().await;
        db.connect()
            .await
            .expect("connect")
            .execute(
                "INSERT INTO verifications VALUES ('v9','q1','human','fail','[\"answer\",\"explanation\"]','review',NULL,'h1','2026-02-01T00:00:00Z')",
                (),
            )
            .await
            .expect("insert fail");
        let s = crate::state::DbState::detached(db);
        let q1 = get_question(&s, "q1").await.expect("q1").expect("present");
        assert!(!q1.verified, "a later fail must void the earlier pass");
        let only = QuestionFilter {
            verified: Some(true),
            ..Default::default()
        };
        let (_, total) = list_questions(&s, &only, 1, 50).await.expect("filter");
        assert_eq!(total, 0);
    }

    #[tokio::test]
    async fn novel_question_verified_derives_from_the_log() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let rows = list_novel_questions(&s, "lekki", None)
            .await
            .expect("novel questions");
        let nq1 = rows.iter().find(|q| q.id == "nq1").expect("nq1");
        assert!(nq1.verified);
        let nq2 = rows.iter().find(|q| q.id == "nq2").expect("nq2");
        assert!(!nq2.verified);
    }

    #[tokio::test]
    async fn get_exam_maps_row_and_missing_is_none() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let jamb = get_exam(&s, "JAMB").await.expect("query").expect("present");
        assert_eq!(jamb.name, "Joint Admissions");
        assert_eq!(jamb.countries, vec!["NG"]);
        assert_eq!(jamb.duration_minutes, Some(120));
        assert!(get_exam(&s, "WASSCE-2099").await.expect("query").is_none());
    }

    #[tokio::test]
    async fn requirements_are_country_scoped() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let ng = list_requirements(&s, "JAMB", "NG").await.expect("query");
        assert_eq!(ng.len(), 2);
        assert_eq!(ng[0].group, "core");
        assert_eq!(ng[0].min_select, 1);
        assert_eq!(ng[0].subjects, vec!["use-of-english"]);
        let gh = list_requirements(&s, "JAMB", "GH").await.expect("query");
        assert!(gh.is_empty(), "JAMB states nothing for GH");
    }

    #[tokio::test]
    async fn subject_stats_count_verified_under_the_same_rule() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let jamb = subject_stats(&s, "JAMB", None).await.expect("query");
        // physics holds q1 (verified, 1.0) and q2 (unverified, 2.0).
        let physics = jamb.get("physics").expect("physics has rows");
        assert_eq!(physics.held, 2);
        assert_eq!(physics.verified, 1);
        assert_eq!(physics.distinct_marks, 2);
        // The same subject under WAEC holds only q3, verified against a stale hash.
        let waec = subject_stats(&s, "WAEC", None).await.expect("query");
        let physics = waec.get("physics").expect("waec physics");
        assert_eq!(physics.held, 1);
        assert_eq!(physics.verified, 0, "a stale hash is not verified");
    }

    #[tokio::test]
    async fn a_country_scope_restricts_nothing_while_no_topic_is_listed() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        // topic_countries is empty, so a scope is a no-op, not an exclusion.
        let unscoped = subject_stats(&s, "JAMB", None).await.expect("query");
        let scoped = subject_stats(&s, "JAMB", Some("GH")).await.expect("query");
        assert_eq!(
            unscoped.get("physics").map(|p| p.held),
            scoped.get("physics").map(|p| p.held)
        );
    }

    #[tokio::test]
    async fn get_subject_maps_row_and_missing_is_none() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let subject = get_subject(&s, "JAMB", "physics")
            .await
            .expect("query")
            .expect("present");
        assert_eq!(subject.name, "Physics");
        assert!(!subject.is_compulsory);
        assert!(get_subject(&s, "JAMB", "nope")
            .await
            .expect("query")
            .is_none());
    }

    #[tokio::test]
    async fn subject_rows_returns_the_whole_pool_verified_flag_and_all() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let rows = subject_rows(&s, "JAMB", "physics", None)
            .await
            .expect("query");
        assert_eq!(rows.len(), 2, "no page cap: the whole pool");
        let q1 = rows.iter().find(|q| q.id == "q1").expect("q1");
        assert!(q1.verified);
        let q2 = rows.iter().find(|q| q.id == "q2").expect("q2");
        assert!(!q2.verified);
    }

    #[tokio::test]
    async fn list_syllabus_groups_subtopics_under_their_topic() {
        let db = local_exams_db().await;
        let s = crate::state::DbState::detached(db);
        let topics = list_syllabus(&s, "JAMB", "mathematics")
            .await
            .expect("query");
        let geometry = topics
            .iter()
            .find(|t| t.slug == "geometry")
            .expect("geometry");
        assert_eq!(geometry.subtopics, vec!["geometry-basics"]);
        let algebra = topics
            .iter()
            .find(|t| t.slug == "algebra")
            .expect("algebra");
        assert!(
            algebra.subtopics.is_empty(),
            "a topic with no subtopics is carried, not dropped"
        );
    }

    #[tokio::test]
    async fn fetch_rows_refuses_anything_off_the_allowlist() {
        let s = crate::state::DbState::detached(local_exams_db().await);
        // A catalog table is reachable, so the guard is not refusing everything.
        assert!(fetch_rows(&s, "exams", 5).await.is_ok());
        // Credential, answer-bearing, and engine tables are refused before any
        // SQL runs, so this holds even though the harness never created them.
        for t in [
            "api_keys",
            "dashboard_users",
            "sessions",
            "meta",
            "questions",
            "novel_questions",
            "__turso_internal_mvcc_meta",
            "turso_sync_last_change_id",
        ] {
            assert!(
                matches!(
                    fetch_rows(&s, t, 5).await,
                    Err(crate::error::AppError::NotFound)
                ),
                "{t} must be refused"
            );
        }
    }

    #[tokio::test]
    async fn fetch_table_names_lists_only_the_allowlist() {
        let s = crate::state::DbState::detached(local_exams_db().await);
        let names = fetch_table_names(&s).await.expect("names");
        assert!(names.contains(&"exams".to_string()));
        assert!(names.contains(&"subjects".to_string()));
        assert!(
            names
                .iter()
                .all(|n| crate::core::catalog::is_introspectable(n)),
            "a name outside the allowlist leaked: {names:?}"
        );
    }
}
