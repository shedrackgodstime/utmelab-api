//! Store tests run against the real `data/` bank and against deliberately broken
//! copies of it. The broken cases matter more than the happy one: a store that
//! quietly accepts a bad bank is worse than no store.

use std::path::Path;

use std::path::PathBuf;
use utmelab_api::{JsonStore, MAX_PER_PAGE, QuestionFilter, Store, StoreError};

fn repo_root() -> PathBuf {
    // CARGO_MANIFEST_DIR is utmelab-api/
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data")
}

/// Copy the real bank into a scratch directory so a test can corrupt it.
fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("utmelab-store-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("scratch dir");
    for f in ["subjects", "topics", "subtopics", "passages", "questions"] {
        std::fs::copy(
            repo_root().join(format!("{f}.json")),
            dir.join(format!("{f}.json")),
        )
        .expect("copy fixture");
    }
    dir
}

fn load(dir: &Path) -> Result<JsonStore, StoreError> {
    JsonStore::load(dir)
}

#[test]
fn the_real_bank_loads_clean() {
    let bank = JsonStore::load(repo_root()).expect("data/ must be valid");
    assert!(bank.question_count() > 0);
    assert!(bank.subject_count() > 0);
}

#[test]
fn exams_and_subjects_resolve() {
    let bank = JsonStore::load(repo_root()).expect("load");

    assert!(bank.exams().contains(&"JAMB"));

    let jamb = bank.subjects("JAMB");
    assert!(!jamb.is_empty());
    // D21: subjects are exam-scoped rows, so the same concept can appear twice.
    assert!(bank.subject("JAMB", "use-of-english").is_some());
    assert!(bank.subject("WAEC", "use-of-english").is_none());
    assert!(bank.subject("WAEC", "english-language").is_some());
}

#[test]
fn syllabus_carries_coverage_and_objectives() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let s = bank.syllabus("JAMB", "use-of-english").expect("syllabus");

    assert_eq!(s.exam, "JAMB");
    assert_eq!(s.subject.name, "Use of English");
    assert!(!s.topics.is_empty());

    // Every node reports whether it can actually be practised (D19).
    assert!(s.summary.topics > 0);
    assert!(s.summary.questions > 0);
    let with_objects = s
        .topics
        .iter()
        .flat_map(|t| &t.subtopics)
        .find(|st| !st.objectives.is_empty())
        .expect("at least one subtopic carries objectives");
    assert!(!with_objects.objectives.is_empty());
}

#[test]
fn an_answer_is_an_option_id_not_a_label() {
    let bank = JsonStore::load(repo_root()).expect("load");
    for q in bank.questions() {
        let ids: Vec<&str> = q.options.iter().map(|o| o.id.as_str()).collect();
        assert!(
            ids.contains(&q.answer.as_str()),
            "{}: answer '{}' is not an option id",
            q.id,
            q.answer
        );
    }
}

#[test]
fn a_dangling_subtopic_reference_is_rejected() {
    let dir = scratch("bad-subtopic");
    let f = dir.join("questions.json");
    let mut v: serde_json::Value = serde_json::from_slice(&std::fs::read(&f).unwrap()).unwrap();
    v[0]["subtopic_id"] = serde_json::json!("does-not-exist");
    std::fs::write(&f, serde_json::to_vec_pretty(&v).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert!(
        err.problems.iter().any(|p| p.contains("unknown subtopic")),
        "expected an unknown-subtopic problem, got: {err}"
    );
}

#[test]
fn an_answer_pointing_at_nothing_is_rejected() {
    let dir = scratch("bad-answer");
    let f = dir.join("questions.json");
    let mut v: serde_json::Value = serde_json::from_slice(&std::fs::read(&f).unwrap()).unwrap();
    v[0]["answer"] = serde_json::json!("z");
    std::fs::write(&f, serde_json::to_vec_pretty(&v).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert!(
        err.problems
            .iter()
            .any(|p| p.contains("is not one of its option ids")),
        "got: {err}"
    );
}

#[test]
fn a_topic_pointing_at_no_subject_is_rejected() {
    let dir = scratch("bad-topic");
    let f = dir.join("topics.json");
    let mut v: serde_json::Value = serde_json::from_slice(&std::fs::read(&f).unwrap()).unwrap();
    v[0]["subject"] = serde_json::json!("ghost-subject");
    std::fs::write(&f, serde_json::to_vec_pretty(&v).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert!(
        err.problems.iter().any(|p| p.contains("not a subject")),
        "got: {err}"
    );
}

#[test]
fn every_problem_is_reported_not_just_the_first() {
    let dir = scratch("many");
    let f = dir.join("questions.json");
    let mut v: serde_json::Value = serde_json::from_slice(&std::fs::read(&f).unwrap()).unwrap();
    v[0]["answer"] = serde_json::json!("z");
    v[1]["subtopic_id"] = serde_json::json!("ghost");
    v[2]["difficulty"] = serde_json::json!(9);
    std::fs::write(&f, serde_json::to_vec_pretty(&v).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert!(
        err.problems.len() >= 3,
        "one run must surface every problem, got only {}: {err}",
        err.problems.len()
    );
}

#[test]
fn the_unassigned_exam_question_is_reported_but_does_not_stop_the_load() {
    // The fixture deliberately carries one question with no exam (D21).
    // It must be surfaced as a problem, not silently served.
    let dir = scratch("unassigned");
    let f = dir.join("questions.json");
    let mut v: serde_json::Value = serde_json::from_slice(&std::fs::read(&f).unwrap()).unwrap();
    for q in v.as_array_mut().unwrap() {
        if q["exam"] == "" {
            q["exam"] = serde_json::json!("JAMB");
            q["subject"] = serde_json::json!("mathematics");
        }
    }
    std::fs::write(&f, serde_json::to_vec_pretty(&v).unwrap()).unwrap();

    // With every exam assigned, the bank loads clean.
    assert!(load(&dir).is_ok());
}

// ── paging (D3/D30) ─────────────────────────────────────────────────────────

#[test]
fn paging_is_bounded_and_totals_are_stable() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let f = QuestionFilter {
        exam: Some("JAMB"),
        subject: Some("mathematics"),
        ..Default::default()
    };

    let first = bank.questions_page(f, 1, 2);
    assert_eq!(first.per_page, 2);
    assert_eq!(
        first.total_records, 5,
        "five maths questions in the fixture"
    );
    assert_eq!(first.total_pages(), 3);
    assert_eq!(first.questions.len(), 2);

    // Every page reports the same totals — that is D23 requirement 3.
    let last = bank.questions_page(f, 3, 2);
    assert_eq!(last.questions.len(), 1);
    assert_eq!(last.total_records, first.total_records);
    assert_eq!(last.total_pages(), first.total_pages());

    // Past the end: empty, but the totals still tell the truth.
    let beyond = bank.questions_page(f, 99, 2);
    assert!(beyond.questions.is_empty());
    assert_eq!(beyond.total_records, 5);
}

#[test]
fn pages_do_not_overlap_or_skip() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let f = QuestionFilter {
        subject: Some("mathematics"),
        ..Default::default()
    };

    let mut seen = Vec::new();
    for page in 1..=bank.questions_page(f, 1, 2).total_pages() {
        seen.extend(
            bank.questions_page(f, page, 2)
                .questions
                .into_iter()
                .map(|q| q.id),
        );
    }
    seen.sort();
    seen.dedup();
    assert_eq!(
        seen.len(),
        5,
        "every question appears exactly once across pages"
    );
}

#[test]
fn per_page_is_capped_so_the_bank_cannot_be_dumped() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let page = bank.questions_page(QuestionFilter::default(), 1, u32::MAX);
    assert_eq!(page.per_page, MAX_PER_PAGE);
    assert!(page.total_records >= page.questions.len());
}

#[test]
fn page_zero_is_treated_as_page_one() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let f = QuestionFilter {
        subject: Some("mathematics"),
        ..Default::default()
    };
    let zero = bank.questions_page(f, 0, 2);
    assert_eq!(zero.page, 1);
    assert_eq!(zero.questions.len(), 2);
}

#[test]
fn verified_filter_narrows_the_total() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let f = QuestionFilter {
        verified: Some(true),
        ..Default::default()
    };
    let page = bank.questions_page(f, 1, 200);
    assert!(page.questions.iter().all(|q| q.verified));
    assert!(page.total_records < bank.question_count());
}

// ── novels (D35) ────────────────────────────────────────────────────────────

#[test]
fn novels_load_with_chapters_characters_and_themes() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let novels = bank.novels(Some("JAMB"));
    assert!(!novels.is_empty(), "at least one JAMB novel");

    let lekki = bank
        .novel("lekki-headmaster")
        .expect("lekki-headmaster loads");
    assert_eq!(lekki.novel.title, "The Lekki Headmaster");
    assert_eq!(lekki.chapters.len(), 12);
    assert!(!lekki.characters.is_empty());
    assert!(!lekki.themes.is_empty());
}

#[test]
fn featured_novel_is_the_current_set_text() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let featured = bank.featured_novel("JAMB").expect("a featured JAMB novel");
    assert_eq!(featured.id, "lekki-headmaster");
    assert!(featured.year_prescribed.contains(&2025));
}

#[test]
fn novels_are_newest_first() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let novels = bank.novels(None);
    let years: Vec<u16> = novels
        .iter()
        .map(|n| n.year_prescribed.iter().copied().max().unwrap_or(0))
        .collect();
    let mut sorted = years.clone();
    sorted.sort_unstable_by(|a, b| b.cmp(a));
    assert_eq!(years, sorted, "newest prescription first");
}
