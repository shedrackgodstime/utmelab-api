//! Pure catalog logic. No axum, no database client: every function here
//! is a total transformation of plain data, unit-testable with no runtime.

use super::models::{
    Question, RenderedNovelQuestion, RenderedQuestion, Subject, Syllabus, SyllabusSubtopic,
    SyllabusSummary, SyllabusTopic, TableRef, TopicNote,
};
use super::papers;

/// Compose a complete URL for a stored figure filename. If the reference is
/// already an absolute URL (https://, http://, data:, or //), it is returned
/// unchanged. Otherwise, the reference is resolved under the host's
/// `/images/` namespace.
pub fn resolve_media_url(url: &str, media_base_url: &str) -> String {
    let trimmed = url.trim();
    if trimmed.starts_with("https://")
        || trimmed.starts_with("http://")
        || trimmed.starts_with("data:")
        || trimmed.starts_with("//")
    {
        trimmed.to_string()
    } else {
        let path = trimmed.trim_start_matches('/');
        // The bank's figures live under the host's `images/` namespace. The
        // book has its own, so a path that already names it is kept as it is.
        let image_path = if path.starts_with("books/") {
            path.to_string()
        } else {
            path.strip_prefix("images/")
                .map_or_else(|| format!("images/{path}"), |rest| format!("images/{rest}"))
        };
        format!("{}/{}", media_base_url.trim_end_matches('/'), image_path)
    }
}

pub fn resolve_rich_text(rt: &mut super::models::RichText, media_base_url: &str) {
    for inline in &mut rt.inline {
        if let super::models::InlineKind::Image { url, .. } = &mut inline.kind {
            *url = resolve_media_url(url, media_base_url);
        }
    }
}

/// Resolve the figure references a section's teaching text carries.
///
/// The teaching text is a JSON document, so the figures inside it are not
/// typed. A figure block holds its asset in `asset_url`, and the rich text
/// around it may hold images of its own. Both are resolved, so a client
/// never sees a stored path.
pub fn resolve_teaching_text(teaching: &mut serde_json::Value, media_base_url: &str) {
    let Some(blocks) = teaching.get_mut("blocks").and_then(|b| b.as_array_mut()) else {
        return;
    };
    for block in blocks.iter_mut() {
        if let Some(asset) = block.get_mut("asset_url").and_then(|a| a.as_str()) {
            let resolved = resolve_media_url(asset, media_base_url);
            if let Some(slot) = block.get_mut("asset_url") {
                *slot = serde_json::Value::String(resolved);
            }
        }
        for field in ["caption", "content", "text"] {
            if let Some(rt) = block.get_mut(field) {
                if let Ok(mut parsed) =
                    serde_json::from_value::<super::models::RichText>(rt.clone())
                {
                    resolve_rich_text(&mut parsed, media_base_url);
                    if let Ok(written) = serde_json::to_value(&parsed) {
                        *rt = written;
                    }
                }
            }
        }
    }
}

/// Resolve every rich-text field a note carries. Notes are served from the
/// same media host as questions and passages, so a stored filename must never
/// leak to a client unresolved.
pub fn resolve_note(note: &mut TopicNote, media_base_url: &str) {
    resolve_rich_text(&mut note.key_takeaway, media_base_url);
    for section in &mut note.sections {
        resolve_rich_text(&mut section.content, media_base_url);
        if let Some(callout) = &mut section.callout {
            resolve_rich_text(&mut callout.text, media_base_url);
        }
    }
    for example in &mut note.worked_examples {
        resolve_rich_text(&mut example.problem_statement, media_base_url);
        resolve_rich_text(&mut example.final_answer, media_base_url);
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

/// Compute a SQL offset without overflowing the public `u32` query bounds.
pub fn page_offset(page: u32, per_page: u32) -> u64 {
    u64::from(page.saturating_sub(1)) * u64::from(per_page)
}

/// [`page_bounds`] over the raw query inputs: absent means page 1, 50 rows.
/// The default page size lives here, once, so no module spells it itself.
pub fn page_query(page: Option<u32>, per_page: Option<u32>) -> (u32, u32) {
    page_bounds(page.unwrap_or(1), per_page.unwrap_or(50))
}

/// Whether an exam offers a subject in `country`. An empty subject scope
/// means every country its exam runs in; a stated one is a subset. This is
/// the outer half of the country rule: a topic cannot be in scope where its
/// subject is not offered.
pub fn subject_offered(subject: &Subject, country: &str) -> bool {
    subject.countries.is_empty()
        || subject
            .countries
            .iter()
            .any(|c| c.eq_ignore_ascii_case(country))
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
                has_note: false,
                note_id: None,
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
            has_note: false,
            note_id: None,
        });
    }

    Syllabus {
        exam: exam.to_owned(),
        subject,
        topics,
        summary,
    }
}

/// The exam and subject whose syllabus a subject offering uses. A board may
/// share another board's syllabus; anything unstated is itself.
pub fn syllabus_owner(exam: &str, slug: &str, subject: &Subject) -> (String, String) {
    match (&subject.syllabus_exam, &subject.syllabus_subject) {
        (Some(syllabus_exam), Some(syllabus_subject)) => {
            (syllabus_exam.clone(), syllabus_subject.clone())
        }
        _ => (exam.to_string(), slug.to_string()),
    }
}

pub fn attach_notes_to_syllabus(
    syllabus: &mut Syllabus,
    notes: &std::collections::HashMap<(String, Option<String>), String>,
) {
    for t in &mut syllabus.topics {
        if let Some(note_id) = notes.get(&(t.slug.clone(), None)) {
            t.has_note = true;
            t.note_id = Some(note_id.clone());
        }
        for st in &mut t.subtopics {
            if let Some(note_id) = notes.get(&(t.slug.clone(), Some(st.slug.clone()))) {
                st.has_note = true;
                st.note_id = Some(note_id.clone());
            }
        }
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
        let base = crate::config::DEFAULT_MEDIA_BASE_URL;
        assert_eq!(
            resolve_media_url("0123456789abcdef.png", base),
            "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/images/0123456789abcdef.png"
        );
        assert_eq!(
            resolve_media_url("/leading/slash.png", base),
            "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/images/leading/slash.png"
        );
        assert_eq!(
            resolve_media_url("images/already-prefixed.png", base),
            "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/images/already-prefixed.png"
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
    fn the_book_keeps_its_own_directory() {
        let base = crate::config::DEFAULT_MEDIA_BASE_URL;
        assert_eq!(
            resolve_media_url("books/secondary_physics/abc123.jpg", base),
            "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/books/secondary_physics/abc123.jpg"
        );
    }

    #[test]
    fn teaching_text_resolves_its_figures() {
        let base = crate::config::DEFAULT_MEDIA_BASE_URL;
        let mut teaching = serde_json::json!({
            "blocks": [
                {
                    "id": "b-1",
                    "type": "figure",
                    "asset_url": "books/secondary_physics/abc123.jpg",
                    "caption": {"text": "A figure", "inline": []},
                    "alt": "alt"
                },
                {
                    "id": "b-2",
                    "type": "paragraph",
                    "content": {
                        "text": "See the figure.",
                        "inline": [{
                            "start": 4,
                            "len": 0,
                            "kind": "image",
                            "url": "books/secondary_physics/def456.jpg",
                            "position": "above"
                        }]
                    }
                }
            ]
        });
        resolve_teaching_text(&mut teaching, base);
        let blocks = teaching["blocks"].as_array().unwrap();
        assert_eq!(
            blocks[0]["asset_url"],
            "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/books/secondary_physics/abc123.jpg"
        );
        let inline = blocks[1]["content"]["inline"][0]["url"].as_str().unwrap();
        assert_eq!(
            inline,
            "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/books/secondary_physics/def456.jpg"
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

        let r = render(&q, true, crate::config::DEFAULT_MEDIA_BASE_URL);
        match &r.text.inline[0].kind {
            InlineKind::Image { url, .. } => {
                assert_eq!(
                    url,
                    "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/images/stem_diagram.png"
                );
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
                assert_eq!(
                    url,
                    "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/images/keypoint.png"
                );
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
    fn page_offset_handles_the_largest_query_page() {
        assert_eq!(page_offset(u32::MAX, 200), 858_993_458_800);
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
            countries: Vec::new(),
            syllabus_exam: None,
            syllabus_subject: None,
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
        assert!(!s.topics[0].has_note);
        assert!(!s.topics[0].subtopics[0].has_note);
    }

    #[test]
    fn attach_notes_marks_only_the_nodes_that_have_notes() {
        let mut s = assemble_syllabus("JAMB", subject_fixture(), &tree_fixture(), &[], None);
        let mut notes = std::collections::HashMap::new();
        notes.insert(("algebra".to_string(), None), "note_algebra".to_string());
        notes.insert(
            ("algebra".to_string(), Some("linear".to_string())),
            "note_linear".to_string(),
        );

        attach_notes_to_syllabus(&mut s, &notes);

        assert!(s.topics[0].has_note);
        assert_eq!(s.topics[0].note_id.as_deref(), Some("note_algebra"));
        assert!(s.topics[0].subtopics[0].has_note);
        assert_eq!(
            s.topics[0].subtopics[0].note_id.as_deref(),
            Some("note_linear")
        );
        assert!(!s.topics[1].has_note);
        assert!(!s.topics[1].subtopics[0].has_note);
    }

    #[test]
    fn resolve_note_reaches_every_rich_text_field() {
        use crate::core::models::*;
        let image = |url: &str| Inline {
            start: 0,
            len: 0,
            kind: InlineKind::Image {
                url: url.to_string(),
                position: ImagePosition::Above,
                alt: None,
            },
        };
        let rich = |url: &str| RichText {
            text: "see".to_string(),
            inline: vec![image(url)],
        };
        let mut note = TopicNote {
            id: "n".to_string(),
            exam: "JAMB".to_string(),
            subject: "physics".to_string(),
            topic_slug: "motion".to_string(),
            subtopic_slug: None,
            title: "Motion".to_string(),
            read_time_minutes: 3,
            key_takeaway: rich("key.png"),
            sections: vec![NoteSection {
                section_number: 1,
                heading: "One".to_string(),
                content: rich("section.png"),
                callout: Some(NoteCallout {
                    kind: "tip".to_string(),
                    text: rich("callout.png"),
                }),
            }],
            worked_examples: vec![WorkedExample {
                title: "Example".to_string(),
                problem_statement: rich("problem.png"),
                steps: vec![],
                final_answer: rich("answer.png"),
                method_tip: None,
            }],
            formulas: vec![],
            active_recall_checks: vec![],
            examiner_traps: vec![],
            sources: vec![],
            linked_question_ids: vec![],
        };

        resolve_note(&mut note, crate::config::DEFAULT_MEDIA_BASE_URL);

        let url = |rt: &RichText| match &rt.inline[0].kind {
            InlineKind::Image { url, .. } => url.clone(),
            _ => panic!("expected image"),
        };
        let base = crate::config::DEFAULT_MEDIA_BASE_URL.trim_end_matches('/');
        assert_eq!(url(&note.key_takeaway), format!("{base}/images/key.png"));
        assert_eq!(
            url(&note.sections[0].content),
            format!("{base}/images/section.png")
        );
        assert_eq!(
            url(&note.sections[0].callout.as_ref().expect("callout").text),
            format!("{base}/images/callout.png")
        );
        assert_eq!(
            url(&note.worked_examples[0].problem_statement),
            format!("{base}/images/problem.png")
        );
        assert_eq!(
            url(&note.worked_examples[0].final_answer),
            format!("{base}/images/answer.png")
        );
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
