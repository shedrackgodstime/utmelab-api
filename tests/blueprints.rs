//! `GET /api/v1/blueprints/{exam}/{subject}` — opt-in readiness (D63/D68).
//!
//! File-bank router, no network: asserts the endpoint serves the same
//! account the bank layer computes (17/23 ready, incomplete), proves the
//! 404s (unknown subject, subject without rows), and pins the opt-in
//! contract — the default syllabus response carries no expectations.

use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use tower::ServiceExt;
use utmelab_api::{AppState, JsonStore, KeyBackend, KeyStore, RateLimiter, ReportStore, router};

fn state() -> AppState {
    let data = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
    let keys_path =
        std::env::temp_dir().join(format!("utmelab-blueprints-{}.json", std::process::id()));
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

async fn get(path: &str) -> (StatusCode, serde_json::Value) {
    let req = Request::builder()
        .uri(path)
        .body(Body::empty())
        .expect("request");
    let resp = router(state()).oneshot(req).await.expect("router responds");
    let status = resp.status();
    let body = resp.into_body().collect().await.expect("body").to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&body).unwrap_or(serde_json::Value::Null);
    (status, json)
}

#[tokio::test]
async fn maths_blueprint_serves_the_readiness_account() {
    let (status, doc) = get("/api/v1/blueprints/JAMB/mathematics").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(doc["exam"], "JAMB");
    assert_eq!(doc["subject"], "mathematics");
    let topics = doc["topics"].as_array().expect("topics array");
    assert_eq!(topics.len(), 23, "all measured topics served");
    // The account must agree with itself (D68): `ready` is exactly `deduped >=
    // need`, and `complete` is exactly "every topic ready". Asserting the
    // *invariant* rather than a count is deliberate — this test once quoted "17
    // topics" and broke the moment a maths row was tagged, which is content
    // growth, not a regression. The count moves; the rule must not.
    for t in topics {
        let need = t["need"].as_u64().expect("need");
        let deduped = t["deduped"].as_u64().expect("deduped");
        let held = t["held"].as_u64().expect("held");
        let verified = t["verified"].as_u64().expect("verified");
        assert_eq!(
            t["ready"] == true,
            deduped >= need,
            "{} reports ready={} with deduped {deduped} against need {need}",
            t["topic"],
            t["ready"]
        );
        assert!(
            deduped <= verified && verified <= held,
            "held/verified/deduped nest: {}",
            t["topic"]
        );
        assert!(need >= 1, "need is positive: {}", t["topic"]);
        assert_eq!(
            t["method"], "measured-topic",
            "provenance rides every row (D63)"
        );
        assert!(t["source"].is_string(), "source present");
        assert!(t["confidence"].is_string(), "confidence present");
    }
    let ready = topics.iter().filter(|t| t["ready"] == true).count();
    assert_eq!(doc["ready"].as_u64().expect("ready"), ready as u64);
    assert_eq!(doc["total"].as_u64().expect("total"), topics.len() as u64);
    assert_eq!(
        doc["complete"] == true,
        ready == topics.len(),
        "complete means every measured topic is ready, nothing else"
    );
    // The launch-relevant fact: maths is *not* complete, and the bank says so.
    assert_eq!(doc["complete"], false, "maths still has short topics");
    // D71: one cohort, so the predicate stands down and `complete` is coverage
    // arithmetic rather than a promise. Both facts ride the response.
    assert_eq!(doc["governed"], false);
    assert_eq!(doc["cohorts"], serde_json::json!([2025]));
}

#[tokio::test]
async fn unknown_subject_and_unmapped_subject_404() {
    let (status, _) = get("/api/v1/blueprints/JAMB/no-such-subject").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    // Yoruba has a syllabus but no measured rows: honest 404, not an
    // invented all-zero account.
    let (status, _) = get("/api/v1/blueprints/JAMB/yoruba").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}
