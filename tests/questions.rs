//! `GET /api/v1/questions/{id}` — resolving an id we already handed out.
//!
//! The gap this closes: every consumer that *stores* a question id (a saved
//! question, a report receipt, a deep link from our docs) had no route back to
//! the row. The list endpoint cannot serve it, because paging by position is
//! not addressing.
//!
//! These assert the contract that makes it interchangeable with a list item:
//! same shape, same answer-withholding rule, same 401.

use std::sync::{Arc, Mutex, OnceLock};

use axum::body::Body;
use axum::http::{Request, StatusCode};
use tower::ServiceExt;
use utmelab_api::Store as _;
use utmelab_api::{AppState, JsonStore, KeyBackend, KeyStore, RateLimiter, ReportStore, router};

/// A real id, discovered from the bank rather than hardcoded — Ids get renamed
/// (D47 stripped a false claim out of 56 of them), and a test that pins an id
/// fails for a reason that has nothing to do with what it is testing.
fn known() -> String {
    let data = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
    let bank = JsonStore::load(&data).expect("bank loads");
    let page = bank.questions_page(utmelab_api::QuestionFilter::default(), 1, 1);
    page.questions[0].id.clone()
}

fn keys_path() -> std::path::PathBuf {
    std::env::temp_dir().join(format!("utmelab-question-{}-keys.json", std::process::id()))
}

fn state() -> AppState {
    let data = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
    // The key file is deliberately NOT cleared here: every request builds a
    // fresh state, so wiping it would delete the very key the request is
    // presenting. `key()` clears it exactly once, before issuing.
    let keys_path = keys_path();
    let reports_path = std::env::temp_dir().join(format!(
        "utmelab-question-{}-reports.json",
        std::process::id()
    ));
    let _ = std::fs::remove_file(&reports_path);
    AppState {
        bank: Arc::new(JsonStore::load(&data).expect("bank loads")),
        keys: Arc::new(KeyBackend::file(
            KeyStore::open_json(&keys_path).expect("key store"),
        )),
        limiter: Arc::new(Mutex::new(RateLimiter::new())),
        reports: Arc::new(tokio::sync::Mutex::new(
            ReportStore::open(&reports_path).expect("report store"),
        )),
    }
}

async fn json(uri: &str, key: Option<&str>) -> (StatusCode, serde_json::Value) {
    let mut req = Request::builder().uri(uri);
    if let Some(k) = key {
        req = req.header("x-api-key", k);
    }
    let response = router(state())
        .oneshot(req.body(Body::empty()).expect("request"))
        .await
        .expect("router responds");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), 512 * 1024)
        .await
        .expect("body");
    let value = serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null);
    (status, value)
}

/// One throwaway key for the whole binary, issued through the real store so the
/// tests exercise the same path a consumer would.
fn key() -> &'static str {
    static KEY: OnceLock<String> = OnceLock::new();
    KEY.get_or_init(|| {
        let path = keys_path();
        let _ = std::fs::remove_file(&path);
        let mut keys = KeyStore::open_json(&path).expect("key store");
        keys.create("test", 60).expect("key is issued").1
    })
}

#[tokio::test]
async fn a_known_id_resolves_to_that_exact_question() {
    let key = key();
    let (status, body) = json(&format!("/api/v1/questions/{}", known()), Some(key)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["id"], known());
    assert!(body["text"].as_str().is_some_and(|t| !t.is_empty()));
}

#[tokio::test]
async fn it_still_requires_a_key() {
    // It sits on the metered surface, so it must not become a free side door
    // around the rate limit on `/questions`.
    let (status, _) = json(&format!("/api/v1/questions/{}", known()), None).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn an_unknown_id_is_a_404_not_an_empty_question() {
    let key = key();
    let (status, body) = json("/api/v1/questions/q_does_not_exist", Some(key)).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["code"], "question_not_found");
}

#[tokio::test]
async fn the_answer_is_withheld_by_default_and_present_on_request() {
    let key = key();

    let (_, bare) = json(&format!("/api/v1/questions/{}", known()), Some(key)).await;
    assert!(
        bare.get("answer").is_none(),
        "an answer in a default payload gets rendered by somebody, eventually, by accident"
    );

    let (_, opened) = json(
        &format!("/api/v1/questions/{}?include_explanation=true", known()),
        Some(key),
    )
    .await;
    assert!(
        opened.get("answer").is_some(),
        "opted in, so it must be there"
    );
}

#[tokio::test]
async fn it_returns_the_same_shape_as_a_list_item() {
    // The whole point is that a consumer can swap one call for the other
    // without reshaping their code.
    let key = key();
    let (_, single) = json(&format!("/api/v1/questions/{}", known()), Some(key)).await;
    let (_, page) = json("/api/v1/questions?per_page=200", Some(key)).await;

    let listed = page["questions"]
        .as_array()
        .expect("questions array")
        .iter()
        .find(|q| q["id"] == single["id"])
        .expect("the single question must also appear in the list");

    let mut single_keys: Vec<_> = single
        .as_object()
        .expect("object")
        .keys()
        .cloned()
        .collect();
    let mut listed_keys: Vec<_> = listed
        .as_object()
        .expect("object")
        .keys()
        .cloned()
        .collect();
    single_keys.sort();
    listed_keys.sort();
    assert_eq!(
        single_keys, listed_keys,
        "one shape, or consumers must write two renderers"
    );
}

#[tokio::test]
async fn a_withheld_question_is_not_addressable() {
    // A row with no exam is counted on /health but never served. Fetching it by
    // id must not become a way around that (D21).
    let key = key();
    let (status, _) = json("/api/v1/questions/q_unassigned_civic_001", Some(key)).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}
