//! Pure catalog logic. No axum, no database client: every function here
//! is a total transformation of plain data, unit-testable with no runtime.

use super::models::{
    Question, RenderedNovelQuestion, RenderedQuestion, Subject, Syllabus, SyllabusSubtopic,
    SyllabusSummary, SyllabusTopic, TableRef,
};
use super::papers;

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

/// Build the served syllabus: attribute the subject's rows to their
/// subtopics through the tree, count them, and roll the counts up. Pure —
/// the store fetched the tree and the rows, this only judges them.
///
/// `country` keeps only topics whose stated scope includes it (an empty
/// scope means every country). The rows arrive already scoped, so the tree
/// and the counts agree. A row whose subtopic the tree does not state is
/// held, never counted: a topic may not claim what nothing attributes (D68).
pub fn assemble_syllabus(
    exam: &str,
    subject: Subject,
    tree: &[papers::SyllabusTopic],
    rows: &[Question],
    country: Option<&str>,
) -> Syllabus {
    let mut counts: std::collections::HashMap<&str, usize> = std::collections::HashMap::new();
    for q in rows {
        if let Some(st) = q.subtopic_id.as_deref() {
            *counts.entry(st).or_insert(0) += 1;
        }
    }

    let in_scope = |countries: &[String]| match country {
        None => true,
        Some(c) => countries.is_empty() || countries.iter().any(|x| x == c),
    };

    let mut summary = SyllabusSummary {
        topics: 0,
        topics_with_questions: 0,
        subtopics: 0,
        subtopics_with_questions: 0,
        questions: 0,
    };
    let mut topics: Vec<SyllabusTopic> = Vec::new();
    for t in tree {
        if !in_scope(&t.countries) {
            continue;
        }
        summary.topics += 1;
        let mut subtopics: Vec<SyllabusSubtopic> = Vec::with_capacity(t.subtopics.len());
        for st in &t.subtopics {
            let count = counts.get(st.slug.as_str()).copied().unwrap_or(0);
            summary.subtopics += 1;
            if count > 0 {
                summary.subtopics_with_questions += 1;
            }
            subtopics.push(SyllabusSubtopic {
                slug: st.slug.clone(),
                name: st.name.clone(),
                order: st.order,
                question_count: count,
                objectives: st.objectives.clone(),
                countries: t.countries.clone(),
            });
        }
        let count: usize = subtopics.iter().map(|s| s.question_count).sum();
        if count > 0 {
            summary.topics_with_questions += 1;
        }
        summary.questions += count;
        topics.push(SyllabusTopic {
            slug: t.slug.clone(),
            name: t.name.clone(),
            order: t.order,
            weight: t.weight,
            question_count: count,
            objectives: t.objectives.clone(),
            countries: t.countries.clone(),
            subtopics,
        });
    }

    Syllabus {
        exam: exam.to_owned(),
        subject,
        topics,
        summary,
    }
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

    fn subject_fixture() -> Subject {
        Subject {
            slug: "physics".to_string(),
            exam: "JAMB".to_string(),
            name: "Physics".to_string(),
            is_compulsory: false,
            objective_paper_questions: Some(2),
        }
    }

    fn tree_fixture() -> Vec<papers::SyllabusTopic> {
        vec![
            papers::SyllabusTopic {
                slug: "algebra".to_string(),
                name: "Algebra".to_string(),
                order: 1,
                weight: 0,
                objectives: vec!["solve".to_string()],
                countries: vec![],
                subtopics: vec![papers::SyllabusSubtopic {
                    slug: "linear".to_string(),
                    name: "Linear".to_string(),
                    order: 1,
                    objectives: vec![],
                }],
            },
            papers::SyllabusTopic {
                slug: "geometry".to_string(),
                name: "Geometry".to_string(),
                order: 2,
                weight: 0,
                objectives: vec![],
                countries: vec!["NG".to_string()],
                subtopics: vec![papers::SyllabusSubtopic {
                    slug: "shapes".to_string(),
                    name: "Shapes".to_string(),
                    order: 1,
                    objectives: vec![],
                }],
            },
        ]
    }

    #[test]
    fn assemble_syllabus_counts_only_attributed_rows() {
        let mut q = sample_question();
        q.subtopic_id = Some("linear".to_string());
        let mut stray = sample_question();
        stray.id = "q2".to_string();
        stray.subtopic_id = Some("nowhere".to_string());
        let s = assemble_syllabus(
            "JAMB",
            subject_fixture(),
            &tree_fixture(),
            &[q, stray],
            None,
        );
        assert_eq!(s.summary.topics, 2);
        assert_eq!(s.summary.topics_with_questions, 1);
        assert_eq!(s.summary.subtopics, 2);
        assert_eq!(s.summary.subtopics_with_questions, 1);
        assert_eq!(
            s.summary.questions, 1,
            "a row the tree does not place is held, never counted"
        );
        assert_eq!(s.topics[0].question_count, 1);
        assert_eq!(s.topics[1].question_count, 0);
        assert_eq!(s.topics[0].objectives, vec!["solve".to_string()]);
    }

    #[test]
    fn assemble_syllabus_scopes_topics_by_country() {
        let mut q = sample_question();
        q.subtopic_id = Some("linear".to_string());
        let rows = vec![q];

        // GH keeps the unscoped topic and drops the NG-only one.
        let gh = assemble_syllabus(
            "JAMB",
            subject_fixture(),
            &tree_fixture(),
            &rows,
            Some("GH"),
        );
        assert_eq!(gh.summary.topics, 1);
        assert_eq!(gh.topics[0].slug, "algebra");

        // NG keeps both.
        let ng = assemble_syllabus(
            "JAMB",
            subject_fixture(),
            &tree_fixture(),
            &rows,
            Some("NG"),
        );
        assert_eq!(ng.summary.topics, 2);
    }
}
