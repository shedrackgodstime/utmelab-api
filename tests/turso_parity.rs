//! Turso/JSON parity (R8 dual-run proof). Opt-in — runs only when
//! `TURSO_DB_URL + TURSO_DB_TOKEN` are set, so CI (no network) stays green.
//!
//! Boots both stores and asserts identical serving behavior: counts, exams,
//! sample pages, syllabus summaries, subtopic counts, novels, passages.
//! Versions are NOT compared: file fingerprint vs count-hash differ by
//! construction (R7 draft); consumers compare strings only within a source.

use utmelab_api::{Db, JsonStore, QuestionFilter, Store, TursoStore};

fn data_dir() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data")
}

#[tokio::test]
async fn turso_matches_json() {
    let (Some(url), Some(token)) = (
        std::env::var("TURSO_DB_URL").ok(),
        std::env::var("TURSO_DB_TOKEN").ok(),
    ) else {
        eprintln!("skipping turso parity: no Turso env");
        return;
    };
    let json = JsonStore::load(data_dir()).expect("json bank loads");
    let db = Db::connect(&url, &token).await.expect("turso connects");
    let turso = TursoStore::open(db).await.expect("turso bank loads");

    assert_eq!(
        turso.question_count(),
        json.question_count(),
        "question_count"
    );
    assert_eq!(turso.subject_count(), json.subject_count(), "subject_count");
    // Withheld fixture stays file-side (Phase 2 record): Turso carries the
    // same validation-warning notes minus the single partitioned-row note.
    assert_eq!(
        turso.withheld_count() + 1,
        json.withheld_count(),
        "withheld notes differ only by the file-side fixture row"
    );
    assert_eq!(turso.exams(), json.exams(), "exams");
    assert_eq!(
        turso.subtopic_counts(),
        json.subtopic_counts(),
        "subtopic_counts"
    );

    // Sample pages: first page unfiltered + one filtered page.
    let jp = json.questions_page(QuestionFilter::default(), 1, 20);
    let tp = turso.questions_page(QuestionFilter::default(), 1, 20);
    assert_eq!(tp.total_records, jp.total_records, "page total");
    assert_eq!(
        tp.questions.iter().map(|q| &q.id).collect::<Vec<_>>(),
        jp.questions.iter().map(|q| &q.id).collect::<Vec<_>>(),
        "page 1 ids"
    );
    assert_eq!(
        tp.questions
            .iter()
            .map(|q| (q.id.clone(), q.verified, q.content_fingerprint()))
            .collect::<Vec<_>>(),
        jp.questions
            .iter()
            .map(|q| (q.id.clone(), q.verified, q.content_fingerprint()))
            .collect::<Vec<_>>(),
        "page 1 verified+hash"
    );

    let filt = QuestionFilter {
        exam: Some("JAMB"),
        subject: Some("mathematics"),
        ..Default::default()
    };
    let jp = json.questions_page(filt, 1, 50);
    let tp = turso.questions_page(filt, 1, 50);
    assert_eq!(tp.total_records, jp.total_records, "filtered total");
    assert_eq!(
        tp.questions.iter().map(|q| &q.id).collect::<Vec<_>>(),
        jp.questions.iter().map(|q| &q.id).collect::<Vec<_>>(),
        "filtered ids"
    );

    // Syllabus summaries across every exam/subject pair.
    for exam in json.exams() {
        for s in json.subjects(exam) {
            let js = json.syllabus(exam, &s.slug, None);
            let ts = turso.syllabus(exam, &s.slug, None);
            let jt = js.as_ref().map(|x| {
                (
                    x.summary.topics,
                    x.summary.topics_with_questions,
                    x.summary.subtopics,
                    x.summary.subtopics_with_questions,
                    x.summary.questions,
                    x.topics.len(),
                )
            });
            let tt = ts.as_ref().map(|x| {
                (
                    x.summary.topics,
                    x.summary.topics_with_questions,
                    x.summary.subtopics,
                    x.summary.subtopics_with_questions,
                    x.summary.questions,
                    x.topics.len(),
                )
            });
            assert_eq!(tt, jt, "syllabus {exam}/{}", s.slug);
        }
    }

    // Spot rows: same content, same verified derivation.
    for id in [
        "q_claim_2025_mathematics_74199",
        "q_claim_2025_commerce_75064",
        "q_authored_fine_arts_colour_001",
    ] {
        let jq = json.question(id).expect("json has row");
        let tq = turso.question(id).expect("turso has row");
        assert_eq!(tq.answer, jq.answer, "answer {id}");
        assert_eq!(tq.verified, jq.verified, "verified {id}");
        assert_eq!(
            tq.content_fingerprint(),
            jq.content_fingerprint(),
            "hash {id}"
        );
    }

    // Novels + passages.
    assert_eq!(
        turso.novels(None).len(),
        json.novels(None).len(),
        "novels (servable ≥50q both)"
    );
    assert_eq!(
        turso.featured_novel("JAMB").map(|n| n.id.clone()),
        json.featured_novel("JAMB").map(|n| n.id.clone()),
        "featured novel"
    );
    assert!(
        turso.passage("psg_jamb_2025_eng_cloze_3").is_some(),
        "cloze passage present"
    );
}
