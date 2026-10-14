//! `POST /papers` assembly + scoring (D69): refused until complete,
//! deterministic per seed, answers always withheld, scoring stateless.
//!
//! File-bank router, no network. The real bank's maths is incomplete, so
//! refusal is tested against it; the happy path runs on a synthetic
//! two-topic blueprint (expected 1.0 each) where readiness holds.

use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use tower::ServiceExt;
use utmelab_api::{
    AppState, JsonStore, KeyBackend, KeyStore, RateLimiter, ReportStore, Store, router,
};

fn state() -> AppState {
    let data = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
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

#[tokio::test]
async fn incomplete_subject_refuses_with_named_gaps() {
    let (status, doc) = post(
        "/api/v1/papers/JAMB/mathematics?seed=7",
        serde_json::json!({}),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);
    let detail = doc["detail"].as_str().unwrap_or("");
    // All six unready topics named (D69: the response says what's short).
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
    let data = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
    let bank = JsonStore::load(&data).expect("bank loads");
    let bps = vec![
        utmelab_api::Blueprint {
            exam: "JAMB".to_string(),
            subject: "mathematics".to_string(),
            level: "topic".to_string(),
            topic: Some("trigonometry".to_string()),
            section: None,
            members: vec![],
            paper_size: 40,
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
        },
        utmelab_api::Blueprint {
            exam: "JAMB".to_string(),
            subject: "mathematics".to_string(),
            level: "topic".to_string(),
            topic: Some("sets".to_string()),
            section: None,
            members: vec![],
            paper_size: 40,
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
        },
    ];
    let a = utmelab_api::assemble(&bank, &bps, "JAMB", "mathematics", None, 11)
        .expect("synthetic slice is complete");
    let b = utmelab_api::assemble(&bank, &bps, "JAMB", "mathematics", None, 11)
        .expect("same seed rebuilds");
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
    let data = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
    let bank = JsonStore::load(&data).expect("bank loads");
    let bps = vec![utmelab_api::Blueprint {
        exam: "JAMB".to_string(),
        subject: "mathematics".to_string(),
        level: "topic".to_string(),
        topic: Some("sets".to_string()),
        section: None,
        members: vec![],
        paper_size: 40,
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
    }];
    let paper = utmelab_api::assemble(&bank, &bps, "JAMB", "mathematics", None, 3)
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
