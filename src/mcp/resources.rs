//! Resource URIs and their reads.
//!
//! A resource is a catalog read, addressed by `utmelab://catalog/<tail>` where
//! `<tail>` is the `/api/v1` path with the version stripped. The read calls the
//! exact `api::v1` handler the HTTP route mounts, with the same scope check and
//! same `core` render, so a resource and its HTTP twin cannot drift: there is one
//! implementation, and [`read`] only routes to it.
//!
//! A read with no parameters is a concrete resource ([`list`]); a read whose
//! path carries one is a template ([`templates`]). The two lists together
//! mirror [`crate::api::v1`] exactly, which the parity test in `routes` proves.
//!
//! An optional query string parameterises a read using the same names HTTP
//! uses (`country`, `include_explanation`, …). Values are taken verbatim; a
//! client that needs a reserved character should keep it in the path, where
//! the transport has already decoded it.

use std::collections::HashMap;

use axum::extract::{Path, Query, State};
use rmcp::model::{Resource, ResourceTemplate};

use crate::{
    api::v1::{
        blueprints, exams, keys, meta, notes, novels, papers, passages, questions, subjects,
        textbooks, theory, topics,
    },
    auth::{api_key::AuthedKey, Auth},
    error::AppError,
    state::DbState,
};

/// The prefix every resource shares. The authority names the surface
/// (`catalog`); the path is the `/api/v1` tail.
const BASE: &str = "utmelab://catalog/";

const JSON: &str = "application/json";

/// Concrete resources: catalog reads that take no parameter.
pub fn list() -> Vec<Resource> {
    vec![
        res(
            "textbooks",
            "Textbooks",
            "Every book, with the subject area and the level it teaches.",
        ),
        res(
            "exam-traps",
            "Examiner traps",
            "The mistakes candidates make, with the evidence behind each one. \
Filter by `exam` or `section_id`.",
        ),
        res(
            "exam-practice",
            "Exam practice",
            "Practice items written in an exam's own wording. Filter by `exam` or `section_id`.",
        ),
        res("exams", "Exams", "Every exam the bank holds."),
        res(
            "novels",
            "Novels",
            "The novel catalog, filterable by `exam`, `year`, `featured`, `category`.",
        ),
        res(
            "passages",
            "Passages",
            "Batch retrieve reading passages by `ids`.",
        ),
        res(
            "questions",
            "Questions",
            "Questions, filterable by `exam`, `subject`, `subtopic`, `year`, `source`, \
             `q`, `verified`, `country`, `include_explanation`, `page`, `per_page`.",
        ),
        res(
            "questions/sample",
            "Sample questions",
            "Sample a random or seeded subset of questions for quick quiz flows.",
        ),
        res(
            "meta/tables",
            "Bank tables",
            "The tables the bank exposes to keys.",
        ),
        res(
            "keys/me",
            "This key",
            "The presenting key's prefix, admin flag and scopes.",
        ),
    ]
}

/// Parameterised reads, one per `/api/v1` path that takes a segment. Together
/// with [`list`] these are the whole keyed read surface.
pub fn templates() -> Vec<ResourceTemplate> {
    vec![
        tmpl(
            "textbooks/{book_id}",
            "Textbook",
            "One book and the chapters it holds.",
        ),
        tmpl(
            "chapters/{chapter_id}",
            "Chapter",
            "One chapter: its sections, its exercises and its exam side.",
        ),
        tmpl(
            "chapters/{chapter_id}/exercises",
            "Chapter exercises",
            "The exercises of a chapter, each with its answer and its solution. \
Filter by `section_id` or `tier`.",
        ),
        tmpl(
            "exams/{exam}/subjects",
            "Exam subjects",
            "Subjects offered by one exam.",
        ),
        tmpl(
            "exams/{exam}/papers",
            "Exam readiness",
            "How an exam is shaped and whether the bank can fill it. `country` scopes it.",
        ),
        tmpl(
            "subjects/{exam}/{slug}",
            "Subject",
            "One subject offering within an exam.",
        ),
        tmpl(
            "subjects/{exam}/{slug}/syllabus",
            "Syllabus",
            "A subject's topic tree with live counts. `country` filters it.",
        ),
        tmpl(
            "subjects/{exam}/{slug}/coverage",
            "Coverage",
            "A subject's counts without the tree. `country` filters it.",
        ),
        tmpl(
            "topics/{exam}/{subject}/{slug}",
            "Topic",
            "One syllabus topic.",
        ),
        tmpl(
            "blueprints/{exam}/{subject}",
            "Blueprints",
            "Measured expectations for a subject.",
        ),
        tmpl("passages/{id}", "Passage", "One reading passage."),
        tmpl(
            "passages/catalog/{exam}/{subject}",
            "Passage catalog",
            "A SQL-paged passage catalog. `page`, `per_page`.",
        ),
        tmpl(
            "novels/{id}",
            "Novel",
            "One novel's detail: chapters, characters, themes.",
        ),
        tmpl(
            "novels/{id}/questions",
            "Novel questions",
            "A novel's questions. `chapter`, `include_explanation`, `page`, `per_page`.",
        ),
        tmpl(
            "questions/{id}",
            "Question",
            "One rendered question. `include_explanation` adds the key.",
        ),
        tmpl(
            "meta/rows/{table}",
            "Table rows",
            "A page of rows from an allowlisted table. `limit` caps it.",
        ),
        tmpl(
            "notes/{exam}/{subject}/{topic_slug}",
            "Topic study note",
            "High-yield study note for a syllabus topic.",
        ),
        tmpl(
            "notes/subtopic/{exam}/{subject}/{subtopic_slug}",
            "Subtopic study note",
            "High-yield study note for a specific syllabus subtopic.",
        ),
        tmpl(
            "theory/{exam}/{subject}",
            "Theory questions list",
            "Paged list of Paper 2 theory questions for a subject.",
        ),
        tmpl(
            "theory/{exam}/{subject}/{id}",
            "Theory question practice view",
            "A Paper 2 theory question with practice view (rubric withheld).",
        ),
        tmpl(
            "theory/{exam}/{subject}/{id}/rubric",
            "Theory question marking rubric",
            "Complete step-by-step examiner marking rubric with M/A/B marks.",
        ),
    ]
}

fn res(tail: &str, name: &str, description: &str) -> Resource {
    Resource::new(format!("{BASE}{tail}"), name)
        .with_description(description)
        .with_mime_type(JSON)
}

fn tmpl(uri_template: &str, name: &str, description: &str) -> ResourceTemplate {
    ResourceTemplate::new(format!("{BASE}{uri_template}"), name)
        .with_description(description)
        .with_mime_type(JSON)
}

/// Unwrap a handler's `Json<T>`, then serialise it. Every read arm returns the
/// same `Json` wrapper, so this is the one place the envelope is opened.
macro_rules! read {
    ($call:expr) => {{
        let axum::Json(value) = $call.await?;
        serde_json::to_value(value).map_err(|e| AppError::Internal(e.to_string()))
    }};
}

/// Read one resource. The URI tail selects the handler; a `?query` string
/// supplies its optional parameters. An unknown path is a 404, never an empty
/// document.
pub async fn read(db: &DbState, auth: &Auth, uri: &str) -> Result<serde_json::Value, AppError> {
    let rest = uri.strip_prefix(BASE).ok_or(AppError::NotFound)?;
    let (path, query) = match rest.split_once('?') {
        Some((path, qs)) => (path, parse_query(qs)),
        None => (rest, HashMap::new()),
    };
    let seg: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
    match seg.as_slice() {
        ["textbooks"] => read!(textbooks::list_textbooks(
            State(db.clone()),
            AuthedKey(auth.clone()),
        )),
        ["textbooks", book_id] => read!(textbooks::get_textbook(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(book_id.to_string()),
        )),
        ["chapters", chapter_id] => read!(textbooks::get_chapter(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(chapter_id.to_string()),
        )),
        ["chapters", chapter_id, "exercises"] => read!(textbooks::list_chapter_exercises(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(chapter_id.to_string()),
            Query(textbooks::ExerciseQuery {
                section_id: opt(&query, "section_id"),
                tier: opt(&query, "tier"),
            }),
        )),
        ["exam-traps"] => read!(textbooks::list_exam_traps(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Query(textbooks::TrapQuery {
                exam: opt(&query, "exam"),
                section_id: opt(&query, "section_id"),
            }),
        )),
        ["exam-practice"] => read!(textbooks::list_exam_practice(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Query(textbooks::RecallQuery {
                exam: opt(&query, "exam"),
                section_id: opt(&query, "section_id"),
            }),
        )),
        ["exams"] => read!(exams::list(State(db.clone()), AuthedKey(auth.clone()))),
        ["exams", exam, "subjects"] => read!(subjects::by_exam(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(exam.to_string()),
        )),
        ["exams", exam, "papers"] => read!(papers::readiness(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(exam.to_string()),
            Query(papers::PapersQuery {
                country: opt(&query, "country"),
            }),
        )),
        ["subjects", exam, slug] => read!(subjects::subject(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((exam.to_string(), slug.to_string())),
        )),
        ["subjects", exam, slug, "syllabus"] => read!(subjects::syllabus(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((exam.to_string(), slug.to_string())),
            Query(subjects::SyllabusQuery {
                country: opt(&query, "country"),
            }),
        )),
        ["subjects", exam, slug, "coverage"] => read!(subjects::coverage(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((exam.to_string(), slug.to_string())),
            Query(subjects::SyllabusQuery {
                country: opt(&query, "country"),
            }),
        )),
        ["topics", exam, subject, slug] => read!(topics::one(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((exam.to_string(), subject.to_string(), slug.to_string())),
        )),
        ["notes", exam, subject, topic_slug] => read!(notes::topic_note(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((
                exam.to_string(),
                subject.to_string(),
                topic_slug.to_string()
            )),
        )),
        ["notes", "subtopic", exam, subject, subtopic_slug] => read!(notes::subtopic_note(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((
                exam.to_string(),
                subject.to_string(),
                subtopic_slug.to_string()
            )),
        )),
        ["theory", exam, subject] => read!(theory::list_theory(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((exam.to_string(), subject.to_string())),
            Query(theory::TheoryListParams {
                year: num(&query, "year")?,
                topic: opt(&query, "topic"),
                section: opt(&query, "section"),
                page: num(&query, "page")?,
                per_page: num(&query, "per_page")?,
            }),
        )),
        ["theory", exam, subject, id] => read!(theory::get_theory(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((exam.to_string(), subject.to_string(), id.to_string())),
            Query(theory::TheoryGetParams {
                include_rubric: flag(&query, "include_rubric")?,
            }),
        )),
        ["theory", exam, subject, id, "rubric"] => read!(theory::get_theory_rubric(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((exam.to_string(), subject.to_string(), id.to_string())),
        )),
        ["blueprints", exam, subject] => read!(blueprints::list(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((exam.to_string(), subject.to_string())),
        )),
        ["passages"] => read!(passages::list(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Query(passages::BatchQuery {
                ids: opt(&query, "ids"),
            }),
        )),
        ["passages", "catalog", exam, subject] => read!(passages::catalog(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((exam.to_string(), subject.to_string())),
            Query(passages::CatalogQuery {
                page: num(&query, "page")?,
                per_page: num(&query, "per_page")?,
            }),
        )),
        ["passages", id] => read!(passages::one(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(id.to_string()),
        )),
        ["novels"] => read!(novels::list(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Query(novels::List {
                exam: opt(&query, "exam"),
                year: num(&query, "year")?,
                featured: flag(&query, "featured")?,
                category: opt(&query, "category"),
                page: num(&query, "page")?,
                per_page: num(&query, "per_page")?,
            }),
        )),
        ["novels", id] => read!(novels::detail(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(id.to_string()),
        )),
        ["novels", id, "questions"] => read!(novels::questions(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(id.to_string()),
            Query(novels::Questions {
                chapter: num(&query, "chapter")?,
                include_explanation: flag(&query, "include_explanation")?,
                page: num(&query, "page")?,
                per_page: num(&query, "per_page")?,
            }),
        )),
        ["questions"] => read!(questions::list(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Query(questions::List {
                topic: opt(&query, "topic"),
                subtopic: opt(&query, "subtopic"),
                exam: opt(&query, "exam"),
                subject: opt(&query, "subject"),
                verified: flag(&query, "verified")?,
                year: num(&query, "year")?,
                source: opt(&query, "source"),
                q: opt(&query, "q"),
                country: opt(&query, "country"),
                include_explanation: flag(&query, "include_explanation")?,
                include_passage: flag(&query, "include_passage")?,
                page: num(&query, "page")?,
                per_page: num(&query, "per_page")?,
            }),
        )),
        ["questions", "sample"] => read!(questions::sample(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Query(questions::SampleParams {
                exam: opt(&query, "exam").unwrap_or_default(),
                subject: opt(&query, "subject").unwrap_or_default(),
                count: num(&query, "count")?,
                seed: num(&query, "seed")?,
                verified: flag(&query, "verified")?,
                topic: opt(&query, "topic"),
                subtopic: opt(&query, "subtopic"),
                year: num(&query, "year")?,
                country: opt(&query, "country"),
                include_explanation: flag(&query, "include_explanation")?,
                include_passage: flag(&query, "include_passage")?,
            }),
        )),
        ["questions", id] => read!(questions::one(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(id.to_string()),
            Query(questions::Detail {
                include_explanation: flag(&query, "include_explanation")?,
                include_passage: flag(&query, "include_passage")?,
            }),
        )),
        ["meta", "tables"] => read!(meta::tables(State(db.clone()), AuthedKey(auth.clone()))),
        ["meta", "rows", table] => read!(meta::rows(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(table.to_string()),
            Query(meta::RowsParams {
                limit: num(&query, "limit")?,
            }),
        )),
        ["keys", "me"] => read!(keys::me(AuthedKey(auth.clone()))),
        _ => Err(AppError::NotFound),
    }
}

fn parse_query(qs: &str) -> HashMap<String, String> {
    qs.split('&')
        .filter_map(|pair| pair.split_once('='))
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

fn opt(query: &HashMap<String, String>, key: &str) -> Option<String> {
    query.get(key).cloned()
}

fn num<T: std::str::FromStr>(
    query: &HashMap<String, String>,
    key: &str,
) -> Result<Option<T>, AppError> {
    match query.get(key) {
        None => Ok(None),
        Some(v) => v
            .parse()
            .map(Some)
            .map_err(|_| AppError::BadRequest(format!("{key} must be a number"))),
    }
}

fn flag(query: &HashMap<String, String>, key: &str) -> Result<Option<bool>, AppError> {
    match query.get(key).map(String::as_str) {
        None => Ok(None),
        Some("true" | "1") => Ok(Some(true)),
        Some("false" | "0") => Ok(Some(false)),
        Some(_) => Err(AppError::BadRequest(format!("{key} must be true or false"))),
    }
}
