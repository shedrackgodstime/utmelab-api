//! Pure catalog logic. No axum, no database client: every function here
//! is a total transformation of plain data, unit-testable with no runtime.

use super::models::{Question, RenderedNovelQuestion, RenderedQuestion, TableRef};

/// Present one novel quiz row. Same withholding contract as [`render`];
/// `novel_id` is stamped by the caller — the stored row does not carry it.
pub fn render_novel_question(
    novel_id: &str,
    q: &super::models::NovelQuestion,
    include_explanation: bool,
) -> RenderedNovelQuestion {
    RenderedNovelQuestion {
        id: q.id.clone(),
        novel_id: novel_id.to_owned(),
        chapter_number: q.chapter_number,
        text: q.text.clone(),
        options: q.options.clone(),
        answer: include_explanation.then(|| q.answer.clone()),
        explanation: include_explanation.then(|| q.explanation.clone()).flatten(),
        verified: q.verified,
    }
}

pub fn to_refs(names: Vec<String>) -> Vec<TableRef> {
    names.into_iter().map(|name| TableRef { name }).collect()
}

/// Tables a key may see through the meta surface. Deny by default: a name
/// absent here is invisible, so a table added later cannot leak just by being
/// left off a deny list.
///
/// Deliberately absent: `api_keys`, `dashboard_users`, `sessions` (credential
/// and token hashes), `meta` (server config), `questions` and
/// `novel_questions` (carry the answer and working the read paths withhold),
/// and `reports`/`verifications` (who filed or verified what). Engine tables
/// (`turso_*`, `__turso_*`) are never here.
pub const INTROSPECTABLE_TABLES: &[&str] = &[
    "subjects",
    "exams",
    "topics",
    "subtopics",
    "blueprints",
    "passages",
    "countries",
    "exam_requirements",
    "topic_countries",
    "novels",
    "novel_chapters",
    "novel_characters",
    "novel_themes",
];

/// Whether `name` may be listed or dumped through the meta surface. The one
/// gate both the list and the row endpoints consult.
pub fn is_introspectable(name: &str) -> bool {
    INTROSPECTABLE_TABLES.contains(&name)
}

/// Normalize paging inputs. Page numbers below 1 count as 1; sizes
/// clamp to 1–200. One rule shared by the store query and the response
/// envelope so they can never disagree.
pub fn page_bounds(page: u32, per_page: u32) -> (u32, u32) {
    (page.max(1), per_page.clamp(1, 200))
}

/// Present a stored question. The answer and working ride along only on
/// explicit request; everything else passes through untouched.
pub fn render(q: &Question, include_explanation: bool) -> RenderedQuestion {
    RenderedQuestion {
        id: q.id.clone(),
        exam: q.exam.clone(),
        subject: q.subject.clone(),
        year: q.year,
        source: q.source.clone(),
        text: q.text.clone(),
        options: q.options.clone(),
        section: q.section.clone(),
        passage_id: q.passage_id.clone(),
        marks: q.marks,
        difficulty: q.difficulty,
        verified: q.verified,
        answer: include_explanation.then(|| q.answer.clone()),
        explanation: include_explanation.then(|| q.explanation.clone()).flatten(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_catalog_tables_are_introspectable() {
        for ok in ["subjects", "novels", "passages", "topic_countries"] {
            assert!(is_introspectable(ok), "{ok} should be visible");
        }
        for no in [
            "api_keys",
            "dashboard_users",
            "sessions",
            "meta",
            "questions",
            "novel_questions",
            "reports",
            "verifications",
            "__turso_internal_mvcc_meta",
            "turso_sync_last_change_id",
            "",
        ] {
            assert!(!is_introspectable(no), "{no} must not be visible");
        }
    }

    #[test]
    fn to_refs_preserves_names_in_order() {
        let out = to_refs(vec!["b".to_string(), "a".to_string()]);
        let names: Vec<_> = out.into_iter().map(|t| t.name).collect();
        assert_eq!(names, vec!["b".to_string(), "a".to_string()]);
    }

    fn sample_question() -> Question {
        use crate::core::models::*;
        Question {
            id: "q1".to_string(),
            exam: "JAMB".to_string(),
            subject: "physics".to_string(),
            year: 2025,
            source: "past_paper".to_string(),
            text: RichText {
                text: "What is 2+2?".to_string(),
                inline: vec![],
            },
            options: vec![Choice {
                id: "a".to_string(),
                text: RichText {
                    text: "4".to_string(),
                    inline: vec![],
                },
            }],
            answer: "a".to_string(),
            subtopic_id: None,
            section: None,
            passage_id: None,
            explanation: Some(Explanation {
                key_point: RichText {
                    text: "addition".to_string(),
                    inline: vec![],
                },
                body: RichText {
                    text: "2+2=4".to_string(),
                    inline: vec![],
                },
                trap: None,
            }),
            marks: 1.0,
            difficulty: 2,
            verified: false,
        }
    }

    #[test]
    fn render_withholds_answer_by_default() {
        let r = render(&sample_question(), false);
        assert_eq!(r.id, "q1");
        assert_eq!(r.answer, None);
        assert_eq!(r.explanation, None);
        assert!(!r.verified);
        // Everything else passes through untouched.
        assert_eq!(r.options.len(), 1);
        assert_eq!(r.text.text, "What is 2+2?");
    }

    #[test]
    fn render_includes_answer_on_request() {
        let r = render(&sample_question(), true);
        assert_eq!(r.answer.as_deref(), Some("a"));
        assert!(r.explanation.is_some());
    }

    #[test]
    fn page_bounds_clamps() {
        assert_eq!(page_bounds(0, 0), (1, 1));
        assert_eq!(page_bounds(2, 50), (2, 50));
        assert_eq!(page_bounds(1, 500), (1, 200));
    }
}
