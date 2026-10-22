//! Pure catalog logic. No axum, no database client: every function here
//! is a total transformation of plain data, unit-testable with no runtime.

use super::models::{
    Question, RenderedNovelQuestion, RenderedQuestion, Subject, Syllabus, SyllabusSubtopic,
    SyllabusSummary, SyllabusTopic, TableRef,
};
use super::papers;

/// Compose a complete URL for a stored figure filename. If the reference is
/// already an absolute URL (https://, http://, data:, or //), it is returned
/// unchanged. Otherwise, the reference is resolved against `media_base_url`.
pub fn resolve_media_url(url: &str, media_base_url: &str) -> String {
    let trimmed = url.trim();
    if trimmed.starts_with("https://")
        || trimmed.starts_with("http://")
        || trimmed.starts_with("data:")
        || trimmed.starts_with("//")
    {
        trimmed.to_string()
    } else {
        format!(
            "{}/{}",
            media_base_url.trim_end_matches('/'),
            trimmed.trim_start_matches('/')
        )
    }
}

pub fn resolve_rich_text(rt: &mut super::models::RichText, media_base_url: &str) {
    for inline in &mut rt.inline {
        if let super::models::InlineKind::Image { url, .. } = &mut inline.kind {
            *url = resolve_media_url(url, media_base_url);
        }
    }
}

/// Present one novel quiz row. Same withholding contract as [`render`];
/// `novel_id` is stamped by the caller. The stored row does not carry it.
pub fn render_novel_question(
    novel_id: &str,
    q: &super::models::NovelQuestion,
    include_explanation: bool,
    media_base_url: &str,
) -> RenderedNovelQuestion {
    let mut cloned = q.clone();
    resolve_novel_question(&mut cloned, media_base_url);

    RenderedNovelQuestion {
        id: cloned.id,
        novel_id: novel_id.to_owned(),
        chapter_number: cloned.chapter_number,
        text: cloned.text,
        options: cloned.options,
        answer: include_explanation.then_some(cloned.answer),
        explanation: if include_explanation {
            cloned.explanation
        } else {
            None
        },
        verified: cloned.verified,
    }
}

/// Resolve image references in a stored novel question in place.
pub fn resolve_novel_question(q: &mut super::models::NovelQuestion, media_base_url: &str) {
    resolve_rich_text(&mut q.text, media_base_url);
    for opt in &mut q.options {
        resolve_rich_text(&mut opt.text, media_base_url);
    }
    if let Some(exp) = &mut q.explanation {
        resolve_rich_text(&mut exp.key_point, media_base_url);
        resolve_rich_text(&mut exp.body, media_base_url);
        if let Some(trap) = &mut exp.trap {
            resolve_rich_text(trap, media_base_url);
        }
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
/// clamp to 1 to 200. One rule shared by the store query and the response
/// envelope so they can never disagree.
pub fn page_bounds(page: u32, per_page: u32) -> (u32, u32) {
    (page.max(1), per_page.clamp(1, 200))
}

/// [`page_bounds`] over the raw query inputs: absent means page 1, 50 rows.
/// The default page size lives here, once, so no module spells it itself.
pub fn page_query(page: Option<u32>, per_page: Option<u32>) -> (u32, u32) {
    page_bounds(page.unwrap_or(1), per_page.unwrap_or(50))
}

/// Build the served syllabus: attribute the subject's rows to their
/// subtopics through the tree, count them, and roll the counts up. Pure:
/// the store fetched the tree and the rows, this only judges them.
///
/// `country` keeps only topics whose stated scope includes it (an empty
/// scope means every country). The rows arrive already scoped, so the tree
/// and the counts agree. A row whose subtopic the tree does not state is
/// held, never counted: a topic may not claim what nothing attributes (D68).
/// Assemble syllabus from pre-aggregated subtopic question counts.
pub fn assemble_syllabus_from_counts(
    exam: &str,
    subject: Subject,
    tree: &[papers::SyllabusTopic],
    counts: &std::collections::HashMap<String, usize>,
    country: Option<&str>,
) -> Syllabus {
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
            let count = counts.get(&st.slug).copied().unwrap_or(0);
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

pub fn assemble_syllabus(
    exam: &str,
    subject: Subject,
    tree: &[papers::SyllabusTopic],
    rows: &[Question],
    country: Option<&str>,
) -> Syllabus {
    let mut counts: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    for q in rows {
        if let Some(st) = q.subtopic_id.as_ref() {
            *counts.entry(st.clone()).or_insert(0) += 1;
        }
    }
    assemble_syllabus_from_counts(exam, subject, tree, &counts, country)
}

/// Present a stored question. The answer and working ride along only on
/// explicit request; everything else passes through untouched, with image
/// filenames resolved against `media_base_url`.
pub fn render(q: &Question, include_explanation: bool, media_base_url: &str) -> RenderedQuestion {
    let mut text = q.text.clone();
    resolve_rich_text(&mut text, media_base_url);

    let mut options = q.options.clone();
    for opt in &mut options {
        resolve_rich_text(&mut opt.text, media_base_url);
    }

    let explanation = include_explanation
        .then(|| q.explanation.clone())
        .flatten()
        .map(|mut exp| {
            resolve_rich_text(&mut exp.key_point, media_base_url);
            resolve_rich_text(&mut exp.body, media_base_url);
            if let Some(trap) = &mut exp.trap {
                resolve_rich_text(trap, media_base_url);
            }
            exp
        });

    RenderedQuestion {
        id: q.id.clone(),
        exam: q.exam.clone(),
        subject: q.subject.clone(),
        year: q.year,
        source: q.source.clone(),
        text,
        options,
        subtopic_id: q.subtopic_id.clone(),
        section: q.section.clone(),
        passage_id: q.passage_id.clone(),
        passage: None,
        marks: q.marks,
        difficulty: q.difficulty,
        verified: q.verified,
        answer: include_explanation.then(|| q.answer.clone()),
        explanation,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_catalog_tables_are_introspectable() {
        for ok in ["subjects", "novels", "passages", "topics"] {
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
        let r = render(
            &sample_question(),
            false,
            crate::config::DEFAULT_MEDIA_BASE_URL,
        );
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
        let mut q = sample_question();
        q.subtopic_id = Some("sub-123".to_string());
        let r = render(&q, true, crate::config::DEFAULT_MEDIA_BASE_URL);
        assert_eq!(r.answer.as_deref(), Some("a"));
        assert!(r.explanation.is_some());
        assert_eq!(r.subtopic_id.as_deref(), Some("sub-123"));
    }

    #[test]
    fn resolve_media_url_formats() {
        let base = "https://assets.utmelab.com/images";
        assert_eq!(
            resolve_media_url("0123456789abcdef.png", base),
            "https://assets.utmelab.com/images/0123456789abcdef.png"
        );
        assert_eq!(
            resolve_media_url("/leading/slash.png", base),
            "https://assets.utmelab.com/images/leading/slash.png"
        );
        assert_eq!(
            resolve_media_url("https://myschool.ng/fig.png", base),
            "https://myschool.ng/fig.png"
        );
        assert_eq!(
            resolve_media_url("http://example.com/fig.png", base),
            "http://example.com/fig.png"
        );
        assert_eq!(
            resolve_media_url("//cdn.example.com/fig.png", base),
            "//cdn.example.com/fig.png"
        );
        assert_eq!(
            resolve_media_url("data:image/png;base64,abc", base),
            "data:image/png;base64,abc"
        );
    }

    #[test]
    fn render_resolves_image_filenames_in_all_fields() {
        use crate::core::models::*;
        let mut q = sample_question();
        q.text.inline = vec![Inline {
            start: 0,
            len: 0,
            kind: InlineKind::Image {
                url: "stem_diagram.png".to_string(),
                position: ImagePosition::Above,
                alt: Some("diagram".to_string()),
            },
        }];
        q.options[0].text.inline = vec![Inline {
            start: 0,
            len: 0,
            kind: InlineKind::Image {
                url: "https://external.org/option.png".to_string(),
                position: ImagePosition::Below,
                alt: None,
            },
        }];
        if let Some(exp) = &mut q.explanation {
            exp.key_point.inline = vec![Inline {
                start: 0,
                len: 0,
                kind: InlineKind::Image {
                    url: "keypoint.png".to_string(),
                    position: ImagePosition::Above,
                    alt: None,
                },
            }];
        }

        let r = render(&q, true, "https://assets.utmelab.com/images");
        match &r.text.inline[0].kind {
            InlineKind::Image { url, .. } => {
                assert_eq!(url, "https://assets.utmelab.com/images/stem_diagram.png");
            }
            _ => panic!("expected image"),
        }
        match &r.options[0].text.inline[0].kind {
            InlineKind::Image { url, .. } => {
                assert_eq!(url, "https://external.org/option.png");
            }
            _ => panic!("expected image"),
        }
        let exp = r.explanation.expect("explanation present");
        match &exp.key_point.inline[0].kind {
            InlineKind::Image { url, .. } => {
                assert_eq!(url, "https://assets.utmelab.com/images/keypoint.png");
            }
            _ => panic!("expected image"),
        }
    }

    #[test]
    fn page_bounds_clamps() {
        assert_eq!(page_bounds(0, 0), (1, 1));
        assert_eq!(page_bounds(2, 50), (2, 50));
        assert_eq!(page_bounds(1, 500), (1, 200));
    }

    #[test]
    fn page_query_defaults_then_clamps() {
        assert_eq!(page_query(None, None), (1, 50));
        assert_eq!(page_query(Some(3), None), (3, 50));
        assert_eq!(page_query(None, Some(10)), (1, 10));
        assert_eq!(page_query(Some(0), Some(0)), (1, 1));
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
