//! `POST /papers` assembly + scoring (D69 blueprint gate, D70 count gate):
//! refused until the bank can fill the paper, deterministic per seed, answers
//! always withheld, scoring stateless.
//!
//! File-bank router, no network, against the real bank. Two live subjects
//! cover both gates: mathematics is blueprint-governed and short of complete,
//! so it refuses naming topics; commerce holds no measurement and 78 verified
//! rows, so it serves a labelled 40-question count paper. A synthetic
//! two-topic blueprint covers the blueprint happy path maths cannot yet
//! reach.

use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use tower::ServiceExt;
use utmelab_api::{
    AppState, JsonStore, KeyBackend, KeyStore, PaperMode, RateLimiter, ReportStore, Store,
    assemble_blueprint, blueprint_governs, cohorts, router,
};

fn data_dir() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data")
}

fn state() -> AppState {
    let data = data_dir();
    let keys_path =
        std::env::temp_dir().join(format!("utmelab-papers-{}.json", std::process::id()));
    let _ = std::fs::remove_file(&keys_path);
    let reports_path =
        std::env::temp_dir().join(format!("utmelab-reports-{}.json", std::process::id()));
    let _ = std::fs::remove_file(&reports_path);
    let (bank_tx, bank_rx) = tokio::sync::watch::channel(Arc::new(
        JsonStore::load(&data).expect("bank loads"),
    ) as Arc<dyn utmelab_api::Store>);
    let _bank_sender = bank_tx;
    AppState {
        bank: bank_rx,
        keys: Arc::new(KeyBackend::file(
            KeyStore::open_json(&keys_path).expect("key store"),
        )),
        limiter: Arc::new(Mutex::new(RateLimiter::new())),
        reports: Arc::new(tokio::sync::Mutex::new(
            ReportStore::open(&reports_path).expect("report store"),
        )),
    }
}

async fn post(path: &str, body: serde_json::Value) -> (StatusCode, serde_json::Value) {
    let req = Request::builder()
        .uri(path)
        .method("POST")
        .header("content-type", "application/json")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .expect("request");
    let resp = router(state()).oneshot(req).await.expect("router responds");
    let status = resp.status();
    let bytes = resp.into_body().collect().await.expect("body").to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null);
    (status, json)
}

/// One synthetic measured-topic blueprint row. Test fixture only: it states
/// an expectation so the gate can be exercised, never a bank fact.
fn bp(topic: &str, paper_size: u32) -> utmelab_api::Blueprint {
    utmelab_api::Blueprint {
        exam: "JAMB".to_string(),
        subject: "mathematics".to_string(),
        level: "topic".to_string(),
        topic: Some(topic.to_string()),
        section: None,
        members: vec![],
        paper_size,
        pct: None,
        pct_low: None,
        pct_high: None,
        expected: Some(1.0),
        expected_low: None,
        expected_high: None,
        source: Some("test".to_string()),
        sample: None,
        method: "measured-topic".to_string(),
        confidence: Some("high".to_string()),
        status: "provisional".to_string(),
        note: String::new(),
    }
}

/// D71: a single-cohort bank cannot satisfy a 17-year topic expectation, so
/// the count gate serves mathematics and the blueprint predicate stands down.
#[tokio::test]
async fn single_cohort_subject_serves_a_count_paper_not_an_impossible_blueprint() {
    let (status, doc) = post(
        "/api/v1/papers/JAMB/mathematics?seed=7",
        serde_json::json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        doc["mode"], "count",
        "one cohort cannot balance a 17-year mix"
    );
    assert_eq!(doc["total"], 40);

    // The refusal it would have been is still computed and still reported —
    // the topics the 2025 paper never tested.
    let bank = JsonStore::load(data_dir()).expect("bank loads");
    let blueprints = utmelab_api::load_blueprints(&data_dir()).expect("blueprints load");
    let years = cohorts(&bank, "JAMB", "mathematics", None);
    assert_eq!(years, vec![2025], "the bank holds one cohort");
    let account = utmelab_api::per_topic(&bank, &blueprints, "JAMB", "mathematics", None);
    assert!(!account.governed, "D71: predicate inactive on one cohort");
    assert!(!account.complete, "coverage is 17/23, and it says so");
    assert_eq!(account.ready, 17);
    assert!(
        !blueprint_governs(&blueprints, "JAMB", "mathematics", years.len()),
        "one cohort: not governed"
    );
    assert!(
        blueprint_governs(&blueprints, "JAMB", "mathematics", 2),
        "the same measurement governs the moment a second cohort lands"
    );
    // Governed, the same bank refuses and names all six gaps (D69).
    let refusal = assemble_blueprint(&bank, &blueprints, "JAMB", "mathematics", None, 7)
        .expect_err("governed maths is short");
    let detail = refusal.detail();
    for slug in [
        "binary-operations",
        "loci",
        "measures-of-dispersion",
        "mensuration",
        "polynomials",
        "representation-of-data",
    ] {
        assert!(detail.contains(slug), "gap list names {slug}: {detail}");
    }
}

#[tokio::test]
async fn syntheticmaths_assembles_deterministically_and_scores() {
    // A complete two-topic slice of the real bank, via synthetic
    // expectations — tests the machinery, invents no content.
    let bank = JsonStore::load(data_dir()).expect("bank loads");
    let bps = vec![bp("trigonometry", 1), bp("sets", 1)];
    let a = assemble_blueprint(&bank, &bps, "JAMB", "mathematics", None, 11)
        .expect("synthetic slice is complete");
    let b = assemble_blueprint(&bank, &bps, "JAMB", "mathematics", None, 11)
        .expect("same seed rebuilds");
    assert_eq!(a.mode, PaperMode::Blueprint);
    let ids = |p: &utmelab_api::AssembledPaper| {
        p.sections
            .iter()
            .flat_map(|s| s.questions.iter().map(|q| q.id.clone()))
            .collect::<Vec<_>>()
    };
    assert_eq!(ids(&a), ids(&b), "same seed, same paper");
    assert_eq!(a.total(), 2, "one per topic");
    // Every drawn row is verified (assembly only draws verified).
    for s in &a.sections {
        for q in &s.questions {
            assert!(q.verified, "drawn rows are verified");
        }
    }
}

#[tokio::test]
async fn marking_counts_only_what_was_submitted() {
    let bank = JsonStore::load(data_dir()).expect("bank loads");
    let bps = vec![bp("sets", 1)];
    let paper = assemble_blueprint(&bank, &bps, "JAMB", "mathematics", None, 3)
        .expect("single-topic slice is complete");
    assert_eq!(paper.total(), 1);
    let qid = paper.sections[0].questions[0].id.clone();

    // All correct: full marks.
    let key: std::collections::HashMap<String, String> = paper
        .sections
        .iter()
        .flat_map(|s| s.questions.iter())
        .map(|q| {
            let truth = bank.question(&q.id).expect("row exists").answer.clone();
            (q.id.clone(), truth)
        })
        .collect();
    let (score, marked) = utmelab_api::mark(&paper, &key);
    assert_eq!(score, 1);
    assert!(marked.iter().all(|m| m.correct));

    // Wrong answer: zero, and the key never leaks into the response rows.
    let wrong: std::collections::HashMap<String, String> =
        [(qid.clone(), "zzz-not-an-option".to_string())]
            .into_iter()
            .collect();
    let (score, marked) = utmelab_api::mark(&paper, &wrong);
    assert_eq!(score, 0);
    assert!(!marked[0].correct);
    assert_eq!(marked[0].submitted.as_deref(), Some("zzz-not-an-option"));

    // Unsubmitted: reported unanswered, key withheld.
    let (score, marked) = utmelab_api::mark(&paper, &std::collections::HashMap::new());
    assert_eq!(score, 0);
    assert_eq!(marked[0].submitted, None);
    assert!(!marked[0].correct);
}

/// Every subject the count gate can serve today, and the one it cannot.
/// Pinned from the real bank so a content change that breaks a launch paper
/// fails here rather than in a consumer's hands.
#[test]
fn count_gate_serves_every_subject_but_music_today() {
    let bank = JsonStore::load(data_dir()).expect("bank loads");
    let blueprints = utmelab_api::load_blueprints(&data_dir()).expect("blueprints load");
    let mut served = Vec::new();
    let mut refused = Vec::new();
    for s in bank.subjects("JAMB") {
        match utmelab_api::assemble(&bank, &blueprints, "JAMB", &s.slug, None, 5) {
            Ok(paper) => {
                assert_eq!(
                    paper.total(),
                    s.objective_paper_questions
                        .expect("JAMB states a paper size") as usize,
                    "{} serves a full-length paper",
                    s.slug
                );
                served.push(s.slug.clone());
            }
            Err(_) => refused.push(s.slug.clone()),
        }
    }
    // Music is one verified row short of 40; every other JAMB subject
    // assembles today (D71 put mathematics on the count gate).
    assert_eq!(refused, vec!["music"]);
    assert_eq!(served.len(), 24);
    assert!(served.contains(&"commerce".to_string()));
    assert!(served.contains(&"use-of-english".to_string()));
}

#[tokio::test]
async fn count_paper_is_full_length_labelled_and_keyless() {
    let (status, doc) = post("/api/v1/papers/JAMB/commerce?seed=7", serde_json::json!({})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(doc["mode"], "count", "no measurement, so the paper says so");
    assert_eq!(doc["total"], 40);
    assert_eq!(doc["seed"], 7);
    let questions: Vec<&serde_json::Value> = doc["sections"]
        .as_array()
        .expect("sections")
        .iter()
        .flat_map(|s| s["questions"].as_array().expect("questions").iter())
        .collect();
    assert_eq!(questions.len(), 40);
    let mut ids = std::collections::HashSet::new();
    for q in &questions {
        assert!(
            ids.insert(q["id"].as_str().expect("id")),
            "no duplicate rows"
        );
        assert_eq!(q["verified"], true, "only verified rows sell");
        // The key never rides the paper (D69), on either gate.
        assert!(q["answer"].is_null(), "answers withheld: {q}");
        assert!(q["explanation"].is_null(), "explanations withheld: {q}");
    }
    // Sections are presentational only — grouped by topic, untagged last.
    let sections = doc["sections"].as_array().expect("sections");
    assert!(!sections.is_empty());
    let topics: Vec<&str> = sections
        .iter()
        .filter_map(|s| s["topic"].as_str())
        .collect();
    if let Some(first_empty) = topics.iter().position(|t| t.is_empty()) {
        assert!(
            topics[first_empty..].iter().all(|t| t.is_empty()),
            "untagged rows sort last, never interleaved: {topics:?}"
        );
    }
}

#[tokio::test]
async fn same_seed_same_count_paper_different_seed_differs() {
    let one = post("/api/v1/papers/JAMB/commerce?seed=1", serde_json::json!({})).await;
    let two = post("/api/v1/papers/JAMB/commerce?seed=1", serde_json::json!({})).await;
    let three = post(
        "/api/v1/papers/JAMB/commerce?seed=99",
        serde_json::json!({}),
    )
    .await;
    let ids = |d: &serde_json::Value| -> Vec<String> {
        d["sections"]
            .as_array()
            .expect("sections")
            .iter()
            .flat_map(|s| s["questions"].as_array().expect("questions").iter())
            .map(|q| q["id"].as_str().unwrap_or_default().to_string())
            .collect()
    };
    assert_eq!(ids(&one.1), ids(&two.1), "same seed, same paper");
    assert_ne!(ids(&one.1), ids(&three.1), "a new seed reshuffles");
    assert_eq!(ids(&one.1).len(), 40);
    assert_eq!(ids(&three.1).len(), 40);
}

#[tokio::test]
async fn short_subject_refuses_naming_the_shortfall() {
    // Music holds 39 verified, distinct rows against a 40-question paper.
    let (status, doc) = post("/api/v1/papers/JAMB/music?seed=1", serde_json::json!({})).await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(doc["code"], "paper_not_ready");
    let detail = doc["detail"].as_str().unwrap_or_default();
    assert!(detail.contains("39"), "says what we hold: {detail}");
    assert!(detail.contains("40"), "says what a paper needs: {detail}");
}

#[tokio::test]
async fn subject_without_a_stated_paper_size_refuses_to_invent_one() {
    // WAEC rows state no objective paper size (D50), so no paper can be
    // assembled without inventing a number.
    let (status, doc) = post(
        "/api/v1/papers/WAEC/animal-husbandry?seed=1",
        serde_json::json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);
    let detail = doc["detail"].as_str().unwrap_or_default();
    assert!(
        detail.contains("no objective paper size"),
        "absence is the answer: {detail}"
    );
}

#[tokio::test]
async fn count_paper_scores_statelessly_and_reveals_no_key() {
    let (_, paper) = post("/api/v1/papers/JAMB/commerce?seed=4", serde_json::json!({})).await;
    let ids: Vec<String> = paper["sections"]
        .as_array()
        .expect("sections")
        .iter()
        .flat_map(|s| s["questions"].as_array().expect("questions").iter())
        .map(|q| q["id"].as_str().unwrap_or_default().to_string())
        .collect();
    // Answer every row with the id of nothing in particular: all wrong, and
    // the response may not carry the key to explain why.
    let answers: serde_json::Map<String, serde_json::Value> = ids
        .iter()
        .map(|id| (id.clone(), serde_json::json!("zzz-not-an-option")))
        .collect();
    let (status, doc) = post(
        "/api/v1/papers/JAMB/commerce/score",
        serde_json::json!({"seed": 4, "answers": answers}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(doc["score"], 0);
    assert_eq!(doc["total"], 40);
    assert_eq!(doc["seed"], 4);
    let rows = doc["questions"].as_array().expect("scored rows");
    assert_eq!(rows.len(), 40);
    for r in rows {
        assert_eq!(r["correct"], false);
        assert_eq!(r["submitted"], "zzz-not-an-option");
        assert!(r.get("answer").is_none(), "scoring never returns the key");
    }
    // Scoring an unassemblable subject refuses like assembly does.
    let (status, doc) = post(
        "/api/v1/papers/JAMB/music/score",
        serde_json::json!({"seed": 1, "answers": {}}),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(doc["code"], "paper_not_ready");
}

#[tokio::test]
async fn unknown_subject_is_404_not_a_refusal() {
    let (status, doc) = post(
        "/api/v1/papers/JAMB/not-a-subject?seed=1",
        serde_json::json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(doc["code"], "subject_not_found");
}

#[test]
fn the_gate_needs_both_coverage_and_a_second_cohort() {
    let data = data_dir();
    let blueprints = utmelab_api::load_blueprints(&data_dir()).expect("blueprints load");
    let bank = JsonStore::load(&data).expect("bank loads");

    // Coverage alone is not enough: mathematics' measurement is whole (23
    // topics summing past 40) but its bank holds one cohort.
    let maths_rows: Vec<_> = blueprints
        .iter()
        .filter(|b| b.subject == "mathematics")
        .cloned()
        .collect();
    assert!(
        !blueprint_governs(&maths_rows, "JAMB", "mathematics", 1),
        "whole measurement, single cohort: not governed (D71)"
    );
    assert!(
        blueprint_governs(&maths_rows, "JAMB", "mathematics", 2),
        "whole measurement, two cohorts: governed"
    );

    // Two cohorts alone are not enough either: literature measures 34 of 40
    // seats, so no cohort count makes it govern (D70's coverage condition).
    for cohorts in [2usize, 9] {
        assert!(
            !blueprint_governs(&blueprints, "JAMB", "literature-in-english", cohorts),
            "34 of 40 seats is not a paper at {cohorts} cohorts"
        );
        assert!(
            !blueprint_governs(&blueprints, "JAMB", "use-of-english", cohorts),
            "ranges are not measurements at {cohorts} cohorts"
        );
        assert!(
            !blueprint_governs(&blueprints, "JAMB", "commerce", cohorts),
            "no blueprint rows at {cohorts} cohorts"
        );
    }

    // And the switch is not a fiction: real subjects report one cohort each,
    // so no JAMB subject is governed today.
    for s in bank.subjects("JAMB") {
        assert_eq!(
            cohorts(&bank, "JAMB", &s.slug, None),
            vec![2025],
            "{} claims a cohort it does not hold",
            s.slug
        );
    }
}
