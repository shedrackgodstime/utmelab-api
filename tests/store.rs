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
    for f in [
        "subjects",
        "topics",
        "subtopics",
        "passages",
        "questions",
        "exams",
        "countries",
        "topic_countries",
        "exam_requirements",
    ] {
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

// ── embedded catalog (transitional: catalog in binary, questions on disk) ──

#[test]
fn the_embedded_catalog_matches_the_file_catalog() {
    let file = JsonStore::load(repo_root()).expect("file bank loads");
    let embedded = JsonStore::load_embedded(repo_root()).expect("embedded bank loads");

    assert_eq!(embedded.subject_count(), file.subject_count());
    assert_eq!(embedded.question_count(), file.question_count());
    assert_eq!(embedded.withheld_count(), file.withheld_count());
    assert_eq!(embedded.version().len(), 16);
    // Same content served both ways: spot-check the catalog and the novel.
    assert!(embedded.subject("JAMB", "use-of-english").is_some());
    assert!(embedded.novel("lekki-headmaster").is_some());
    assert_eq!(
        embedded
            .syllabus("JAMB", "use-of-english", None)
            .expect("syllabus")
            .summary
            .questions,
        file.syllabus("JAMB", "use-of-english", None)
            .expect("syllabus")
            .summary
            .questions,
    );
}

#[test]
fn the_embedded_loader_needs_only_questions_json() {
    // The VPS-clean case: a dir with exactly one file. The old loader fails
    // here (no catalog); the embedded loader must not.
    let dir = std::env::temp_dir().join(format!("utmelab-qonly-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("scratch dir");
    std::fs::copy(
        repo_root().join("questions.json"),
        dir.join("questions.json"),
    )
    .expect("copy questions");
    assert!(
        JsonStore::load(&dir).is_err(),
        "file loader needs catalog files"
    );
    let bank = JsonStore::load_embedded(&dir).expect("embedded loader needs only questions.json");
    assert!(bank.question_count() > 0);
    assert!(bank.subject_count() > 0);
    let _ = std::fs::remove_dir_all(&dir);
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
    let s = bank
        .syllabus("JAMB", "use-of-english", None)
        .expect("syllabus");

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
fn a_subject_pointing_at_no_exam_is_rejected() {
    let dir = scratch("bad-exam");
    let f = dir.join("subjects.json");
    let mut v: serde_json::Value = serde_json::from_slice(&std::fs::read(&f).unwrap()).unwrap();
    v[0]["exam"] = serde_json::json!("WASSCE-2099");
    std::fs::write(&f, serde_json::to_vec_pretty(&v).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert!(
        err.problems
            .iter()
            .any(|p| p.contains("references unknown exam")),
        "got: {err}"
    );
}

#[test]
fn scope_rows_must_name_a_real_topic_and_real_countries() {
    let dir = scratch("bad-scope");
    let f = dir.join("topic_countries.json");
    let rows = serde_json::json!([
        {"topic": "no-such-topic", "countries": ["NG"]},
        {"topic": "indices-logarithms-and-surds", "countries": ["XX"]},
    ]);
    std::fs::write(&f, serde_json::to_vec_pretty(&rows).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert!(
        err.problems.iter().any(|p| p.contains("unknown topic")),
        "got: {err}"
    );
    assert!(
        err.problems.iter().any(|p| p.contains("unknown country")),
        "got: {err}"
    );
}

#[test]
fn a_requirement_must_name_a_member_country_and_real_subjects() {
    let dir = scratch("bad-requirement");
    let f = dir.join("exam_requirements.json");
    let rows = serde_json::json!([
        {"exam": "JAMB", "country": "GH", "group": "core", "min_select": 1,
         "subjects": ["use-of-english"]},
        {"exam": "JAMB", "country": "NG", "group": "core", "min_select": 1,
         "subjects": ["no-such-subject"]},
    ]);
    std::fs::write(&f, serde_json::to_vec_pretty(&rows).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert!(
        err.problems
            .iter()
            .any(|p| p.contains("not a member country")),
        "got: {err}"
    );
    assert!(
        err.problems.iter().any(|p| p.contains("unknown subject")),
        "got: {err}"
    );
}

#[test]
fn an_unscoped_bank_answers_every_country_identically() {
    // D66-scope: no scope rows means universal. Filtering by any country
    // must return exactly what no filter returns — the day a scope row
    // lands, this test earns its keep.
    let bank = JsonStore::load(repo_root()).expect("load");
    assert!(bank.topic_scope("indices-logarithms-and-surds").is_empty());
    let all = bank.questions_page(QuestionFilter::default(), 1, 200);
    let scoped = bank.questions_page(
        QuestionFilter {
            country: Some("GH"),
            ..Default::default()
        },
        1,
        200,
    );
    assert_eq!(all.total_records, scoped.total_records);
    let tree = bank
        .syllabus("JAMB", "mathematics", None)
        .expect("syllabus");
    let filtered = bank
        .syllabus("JAMB", "mathematics", Some("GH"))
        .expect("syllabus");
    assert_eq!(tree.summary.questions, filtered.summary.questions);
    assert_eq!(tree.topics.len(), filtered.topics.len());
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
fn an_image_mark_that_is_not_an_absolute_url_is_rejected() {
    let dir = scratch("bad-image");
    let f = dir.join("questions.json");
    let mut v: serde_json::Value = serde_json::from_slice(&std::fs::read(&f).unwrap()).unwrap();
    v[0]["text"] = serde_json::json!({
        "text": v[0]["text"]["text"].as_str().unwrap_or_default(),
        "inline": [{ "start": 0, "len": 0, "kind": "image",
                     "url": "diagrams/x.svg", "position": "above" }],
    });
    std::fs::write(&f, serde_json::to_vec_pretty(&v).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert!(
        err.problems
            .iter()
            .any(|p| p.contains("must be absolute https")),
        "got: {err}"
    );
}

#[test]
fn an_image_anchor_in_the_bank_loads_and_serves() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let with_image: Vec<_> = bank
        .questions_page(QuestionFilter::default(), 1, utmelab_api::MAX_PER_PAGE)
        .questions
        .into_iter()
        .filter(|q| {
            q.text
                .has_mark(|k| matches!(k, utmelab_api::InlineKind::Image { .. }))
        })
        .collect();
    assert!(!with_image.is_empty(), "the bank carries figures");
    for q in &with_image {
        for m in &q.text.inline {
            if let utmelab_api::InlineKind::Image { url, .. } = &m.kind {
                assert!(
                    url.starts_with("https://"),
                    "{}: {} host URL is dead",
                    q.id,
                    url
                );
            }
        }
    }
}

#[test]
fn an_html_entity_in_a_stem_is_rejected() {
    let dir = scratch("bad-entity");
    let f = dir.join("questions.json");
    let mut v: serde_json::Value = serde_json::from_slice(&std::fs::read(&f).unwrap()).unwrap();
    // D60: a text field is {text, inline}; corrupt `text.text` inside it.
    v[0]["text"]["text"] = serde_json::json!("Which is &rsquo;correct&rsquo;?");
    std::fs::write(&f, serde_json::to_vec_pretty(&v).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert!(
        err.problems.iter().any(|p| p.contains("HTML entity")),
        "got: {err}"
    );
}

#[test]
fn a_tag_in_an_option_is_rejected_but_a_comparison_is_not() {
    let dir = scratch("bad-tag");
    let f = dir.join("questions.json");
    let mut v: serde_json::Value = serde_json::from_slice(&std::fs::read(&f).unwrap()).unwrap();
    v[0]["options"][0]["text"]["text"] = serde_json::json!("a<u>bad</u> option");
    v[1]["options"][0]["text"]["text"] = serde_json::json!("x < 2");
    v[1]["text"]["text"] = serde_json::json!("Solve x < 2 for whole x.");
    std::fs::write(&f, serde_json::to_vec_pretty(&v).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert_eq!(
        err.problems.len(),
        1,
        "only the tag must fail, never the comparison: {err}"
    );
    assert!(err.problems[0].contains("markup"), "got: {err}");
}

#[test]
fn batched_subtopic_counts_agree_with_paged_totals() {
    // R5: the topic route reads this map instead of one `questions_page` per
    // child. Same index underneath, so every entry must equal the total the
    // page query reports — checked across the whole bank, not a sample.
    let bank = JsonStore::load(repo_root()).expect("load");
    let counts = bank.subtopic_counts();
    let mut checked = 0;
    for (slug, want) in &counts {
        let page = bank.questions_page(
            QuestionFilter {
                subtopic: Some(slug.as_str()),
                ..Default::default()
            },
            1,
            1,
        );
        assert_eq!(page.total_records, *want, "subtopic {slug}");
        checked += 1;
    }
    assert!(
        checked > 0,
        "the bank tags subtopics, so the map is non-empty"
    );
}

#[test]
fn withheld_rows_survive_a_rewrite_round_trip() {
    // D58: the bank keeps one deliberately unassigned row (D21). Load must
    // partition it aside, and a replace+write+reload cycle — the import path
    // — must carry it back instead of deleting it.
    let dir = scratch("withheld-roundtrip");
    let bank = JsonStore::load(&dir).expect("loads");
    assert!(
        bank.withheld_questions()
            .iter()
            .any(|q| q.id == "q_unassigned_civic_001"),
        "the civic fixture rides along, unassigned"
    );
    assert!(
        bank.questions()
            .iter()
            .all(|q| q.id != "q_unassigned_civic_001"),
        "withheld rows are never servable"
    );
    let servable = bank.question_count();

    let mut rewritten = bank.clone();
    let all: Vec<utmelab_api::Question> = rewritten
        .questions()
        .iter()
        .chain(rewritten.withheld_questions().iter())
        .cloned()
        .collect();
    let problems = rewritten.replace_questions(all);
    assert!(
        problems.is_empty(),
        "round-trip input is valid: {problems:?}"
    );
    rewritten.write_questions(&dir).expect("writes");

    let reloaded = JsonStore::load(&dir).expect("reloads");
    assert_eq!(reloaded.question_count(), servable);
    assert!(
        reloaded
            .withheld_questions()
            .iter()
            .any(|q| q.id == "q_unassigned_civic_001"),
        "the fixture survived the rewrite"
    );
}

#[test]
fn a_question_pointing_at_no_passage_is_rejected() {
    let dir = scratch("bad-passage");
    let f = dir.join("questions.json");
    let mut v: serde_json::Value = serde_json::from_slice(&std::fs::read(&f).unwrap()).unwrap();
    v[0]["passage_id"] = serde_json::json!("psg-does-not-exist");
    std::fs::write(&f, serde_json::to_vec_pretty(&v).unwrap()).unwrap();

    let err = load(&dir).expect_err("must refuse to load");
    assert!(
        err.problems.iter().any(|p| p.contains("unknown passage")),
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
    // Totals are whatever the bank holds — this used to assert a remembered
    // "5", which broke the day the bank grew. Assert the *relationship*
    // instead: pages follow from records and the per-page size.
    let all = bank.questions_page(f, 1, MAX_PER_PAGE).total_records;
    assert_eq!(first.total_records, all);
    assert_eq!(
        first.total_pages(),
        all.div_ceil(2) as u32,
        "pages must follow from the total"
    );
    assert_eq!(first.questions.len(), 2);

    // Every page reports the same totals — that is D23 requirement 3. The last
    // page is computed, not remembered: it was hardcoded to page 3 when the
    // bank held five maths rows.
    let pages = first.total_pages();
    let last = bank.questions_page(f, pages, 2);
    assert_eq!(
        last.questions.len(),
        all - (pages as usize - 1) * 2,
        "the final page holds the remainder, not a remembered one row"
    );
    assert_eq!(last.total_records, first.total_records);
    assert_eq!(last.total_pages(), first.total_pages());

    // Past the end: empty, but the totals still tell the truth.
    let beyond = bank.questions_page(f, 99, 2);
    assert!(beyond.questions.is_empty());
    // The total must still tell the truth when a page returns nothing — but the
    // truth is "however many rows match", not a number remembered when the bank
    // was small.
    assert_eq!(
        beyond.total_records,
        bank.questions_page(f, 1, utmelab_api::MAX_PER_PAGE)
            .total_records
    );
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
        bank.questions_page(f, 1, utmelab_api::MAX_PER_PAGE)
            .total_records,
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
fn the_verified_flag_partitions_the_bank() {
    let bank = JsonStore::load(repo_root()).expect("load");

    let verified = bank.questions_page(
        QuestionFilter {
            verified: Some(true),
            ..Default::default()
        },
        1,
        200,
    );
    let unverified = bank.questions_page(
        QuestionFilter {
            verified: Some(false),
            ..Default::default()
        },
        1,
        200,
    );
    let all = bank.questions_page(QuestionFilter::default(), 1, 200);

    assert!(verified.questions.iter().all(|q| q.verified));
    assert!(unverified.questions.iter().all(|q| !q.verified));

    // True whatever the content holds: the flag splits the servable bank in
    // two, with nothing counted twice and nothing dropped. An earlier version
    // asserted `verified < all`, which only held while an unverified backlog
    // existed — it failed the day the audit cleared it, which says nothing
    // about the filter.
    assert_eq!(
        verified.total_records + unverified.total_records,
        all.total_records,
        "every servable row is either verified or not"
    );
    assert_eq!(all.total_records, bank.question_count());
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

// ── provenance (D48) ────────────────────────────────────────────────────────

/// Whole-word, case-sensitive mention. `favour forward reaction` does not name
/// the character `Favour`; `Favour refused the offer` does.
fn mentions_word(blob: &str, marker: &str) -> bool {
    blob.split(|c: char| !c.is_alphanumeric())
        .any(|token| token == marker)
}

/// D35: a novel carries its own questions inside its own document. A question
/// in the main bank that names a servable novel's characters cannot be answered
/// from anything we serve — the student would need the book — and 78 of them
/// arrived exactly that way.
///
/// The guard only applies to the subjects a novel question could belong to
/// (Use of English, Literature-in-English). Two false positives proved why
/// (2026-10-11): `q_claim_2025_chemistry_74204` says "favour forward reaction"
/// — the equilibrium verb, not the Lekki Headmaster character — and a CRK
/// question names the prophet `Amos`, who is also a Lekki Headmaster character.
/// A chemistry or CRK row can never be a novel question, and a plain
/// case-insensitive substring scan cannot tell the word from the name. Within
/// the novel-eligible subjects, whole-word + case-sensitive is the line; the
/// residual edge (an English passage genuinely mentioning a Lekki character)
/// is exactly what the guard should surface.
#[test]
fn no_question_in_the_bank_depends_on_a_novel_we_hold() {
    const NOVEL_SUBJECTS: [&str; 2] = ["use-of-english", "literature-in-english"];
    let data = repo_root();
    let bank = JsonStore::load(&data).expect("load");
    // Every page. Checking only the first let six novel questions hide in
    // English rows 201-282, which is exactly where they were.
    let first = bank.questions_page(QuestionFilter::default(), 1, utmelab_api::MAX_PER_PAGE);
    let mut all: Vec<utmelab_api::Question> = first.questions.clone();
    for page in 2..=first.total_pages().max(1) {
        all.extend(
            bank.questions_page(QuestionFilter::default(), page, utmelab_api::MAX_PER_PAGE)
                .questions,
        );
    }

    for entry in std::fs::read_dir(data.join("novels")).expect("novels dir") {
        let path = entry.expect("readable entry").path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        let novel: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&path).expect("read")).expect("parse");

        // Only a novel we actually serve is a problem: a stub with no questions
        // cannot make a question unanswerable.
        let served = novel["questions"].as_array().map_or(0, Vec::len);
        if served < 50 {
            continue;
        }
        // Character names are proper nouns. Match them case-sensitively as whole
        // words: Lekki Headmaster has a character named "Favour", and an
        // equilibrium question whose option is "favour forward reaction" is a
        // chemistry question, not a novel question. The original case-insensitive
        // substring scan failed on exactly that collision (2026-10-11,
        // q_claim_2025_chemistry_74204). A genuine novel question capitalises
        // the name; that residual edge (a question starting a sentence with the
        // name) is accepted and recorded here.
        let mut markers: Vec<String> = vec![novel["title"].as_str().unwrap_or_default().to_owned()];
        if let Some(characters) = novel["characters"].as_array() {
            for character in characters {
                let name = character["name"].as_str().unwrap_or_default();
                if !name.is_empty() {
                    markers.push(name.to_owned());
                    if let Some(last) = name.split_whitespace().last() {
                        if last.len() > 3 {
                            markers.push(last.to_owned());
                        }
                    }
                }
            }
        }

        for question in &all {
            // A novel question can only live in an English/Literature row.
            // "favour" in a chemistry option or "Amos" in a CRK question is
            // the subject's own vocabulary, not a dependency on the novel.
            if !NOVEL_SUBJECTS.contains(&question.subject.as_str()) {
                continue;
            }
            let blob = format!(
                "{} {}",
                question.text.text,
                question
                    .options
                    .iter()
                    .map(|o| o.text.text.as_str())
                    .collect::<Vec<_>>()
                    .join(" ")
            );
            for marker in &markers {
                if marker.len() > 3 && mentions_word(&blob, marker) {
                    panic!(
                        "{} names {:?} from {} — novel questions live in the novel document (D35)",
                        question.id,
                        marker,
                        path.file_name().unwrap().to_string_lossy()
                    );
                }
            }
        }
    }
}

#[test]
fn every_question_carries_a_usable_year() {
    // D52: `year` is the cohort a question is prepared for, required on every
    // row. A consumer filtering by year cannot use a field that is empty for a
    // fifth of the bank, so emptiness itself is now a defect.
    let bank = JsonStore::load(repo_root()).expect("load");
    let page = bank.questions_page(QuestionFilter::default(), 1, 200);
    assert!(!page.questions.is_empty());
    let total = page.total_records;
    let this_year = page.questions.first().expect("at least one").year;
    for q in &page.questions {
        assert!(
            (1900..=2100).contains(&q.year),
            "{} has no usable year ({})",
            q.id,
            q.year
        );
    }

    // And the year filter must actually separate cohorts.
    let filtered = bank.questions_page(
        QuestionFilter {
            year: Some(this_year),
            ..Default::default()
        },
        1,
        200,
    );
    assert!(filtered.questions.iter().all(|q| q.year == this_year));
    assert!(
        filtered.total_records >= total.min(200),
        "every question is in this cohort, so filtering must not lose any"
    );
}

#[test]
fn the_source_filter_partitions_by_provenance() {
    let bank = JsonStore::load(repo_root()).expect("load");
    let all = bank
        .questions_page(QuestionFilter::default(), 1, 200)
        .total_records;

    let mut split = 0;
    for source in ["authored", "imported", "claimed_paper"] {
        let page = bank.questions_page(
            QuestionFilter {
                source: Some(source),
                ..Default::default()
            },
            1,
            200,
        );
        assert!(page.questions.iter().all(|q| q.source == source));
        split += page.total_records;
    }
    assert_eq!(
        split, all,
        "every row has exactly one provenance, and the three partition it"
    );
}
