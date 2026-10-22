//! Resource URIs and their reads.
//!
//! A resource is a catalog read, addressed by `utmelab://catalog/<tail>` where
//! `<tail>` is the `/api/v1` path with the version stripped. The read calls the
//! exact `api::v1` handler the HTTP route mounts — same scope check, same
//! `core` render — so a resource and its HTTP twin cannot drift: there is one
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
        blueprints, exams, keys, meta, novels, papers, passages, questions, subjects, topics,
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
        res("exams", "Exams", "Every exam the bank holds."),
        res(
            "novels",
            "Novels",
            "The novel catalog, filterable by `exam`, `year`, `featured`, `category`.",
        ),
        res(
            "questions",
            "Questions",
            "Questions, filterable by `exam`, `subject`, `subtopic`, `year`, `source`, \
             `q`, `verified`, `country`, `include_explanation`, `page`, `per_page`.",
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
        ["blueprints", exam, subject] => read!(blueprints::list(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path((exam.to_string(), subject.to_string())),
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
                subtopic: opt(&query, "subtopic"),
                exam: opt(&query, "exam"),
                subject: opt(&query, "subject"),
                verified: flag(&query, "verified")?,
                year: num(&query, "year")?,
                source: opt(&query, "source"),
                q: opt(&query, "q"),
                country: opt(&query, "country"),
                include_explanation: flag(&query, "include_explanation")?,
                page: num(&query, "page")?,
                per_page: num(&query, "per_page")?,
            }),
        )),
        ["questions", id] => read!(questions::one(
            State(db.clone()),
            AuthedKey(auth.clone()),
            Path(id.to_string()),
            Query(questions::Detail {
                include_explanation: flag(&query, "include_explanation")?,
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
