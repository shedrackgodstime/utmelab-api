//! The spec must not drift from the router.
//!
//! For every path the OpenAPI document advertises, we call it and assert it does
//! not fall through to `route_not_found`. That catches the failure that actually
//! happens — a documented endpoint that was renamed, moved, or never wired.
//!
//! The reverse (a route added but never documented) cannot be asserted here:
//! axum exposes no route introspection. It is caught in review.

use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use tower::ServiceExt;
use utmelab_api::openapi_document;
use utmelab_api::{AppState, JsonStore, KeyStore, RateLimiter, ReportStore, router};

fn state() -> AppState {
    let data = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
    let keys_path =
        std::env::temp_dir().join(format!("utmelab-openapi-{}.json", std::process::id()));
    let _ = std::fs::remove_file(&keys_path);

    let reports_path =
        std::env::temp_dir().join(format!("utmelab-reports-{}.json", std::process::id()));
    let _ = std::fs::remove_file(&reports_path);
    AppState {
        bank: Arc::new(JsonStore::load(&data).expect("bank loads")),
        keys: KeyStore::open_json(&keys_path).expect("key store"),
        limiter: Arc::new(Mutex::new(RateLimiter::new())),
        reports: Arc::new(Mutex::new(
            ReportStore::open(&reports_path).expect("report store"),
        )),
    }
}

/// Substitute real values for path parameters, so the router matches.
fn concrete(path: &str) -> String {
    // `{id}` and `{slug}` name different resources on different paths, so
    // substitute per-path rather than blindly.
    if path.starts_with("/api/v1/passages/") {
        return path.replace("{id}", "psg_jamb_2025_eng_comprehension_1");
    }
    if path.starts_with("/api/v1/questions/{id}") {
        return path.replace("{id}", "q_jamb_2025_math_surds_001");
    }
    if path.starts_with("/api/v1/topics/") {
        return path
            .replace("{exam}", "JAMB")
            .replace("{subject}", "mathematics")
            .replace("{slug}", "indices-logarithms-surds");
    }
    path.replace("{exam}", "JAMB")
        .replace("{slug}", "use-of-english")
        .replace("{id}", "lekki-headmaster")
}

async fn get(path: &str) -> StatusCode {
    let req = Request::builder()
        .uri(path)
        .body(Body::empty())
        .expect("request");
    router(state())
        .oneshot(req)
        .await
        .expect("router responds")
        .status()
}

#[tokio::test]
async fn every_documented_path_resolves() {
    // Assert on the *serialised* document — that is what a client receives,
    // and utoipa's Paths type does not expose iteration.
    let doc: serde_json::Value =
        serde_json::to_value(openapi_document()).expect("document serialises");

    let paths = doc["paths"].as_object().expect("paths object");
    assert!(!paths.is_empty(), "the spec must not be empty");

    for path in paths.keys() {
        let status = get(&concrete(path)).await;
        assert!(
            status != StatusCode::NOT_FOUND,
            "documented path {path} returns 404 — the spec has drifted from the router"
        );
    }
}

#[tokio::test]
async fn unauthenticated_endpoints_really_are_public() {
    for path in [
        "/health",
        "/openapi.json",
        "/api/v1/exams",
        "/api/v1/exams/JAMB/subjects",
        "/api/v1/subjects/JAMB/use-of-english",
        "/api/v1/subjects/JAMB/use-of-english/syllabus",
    ] {
        assert_eq!(
            get(path).await,
            StatusCode::OK,
            "{path} is documented as public but did not answer without a key"
        );
    }
}

#[tokio::test]
async fn authenticated_endpoints_really_do_require_a_key() {
    for path in ["/api/v1/keys/me", "/api/v1/questions?subtopic=surds"] {
        assert_eq!(
            get(path).await,
            StatusCode::UNAUTHORIZED,
            "{path} is documented as keyed but answered without one"
        );
    }
}

#[tokio::test]
async fn an_undocumented_path_is_a_404() {
    assert_eq!(get("/api/v1/not-a-thing").await, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn the_spec_served_is_valid_json_with_the_expected_shape() {
    let req = Request::builder()
        .uri("/openapi.json")
        .body(Body::empty())
        .expect("request");
    let res = router(state()).oneshot(req).await.expect("responds");
    assert_eq!(res.status(), StatusCode::OK);

    let bytes = res.into_body().collect().await.unwrap().to_bytes();
    let v: serde_json::Value = serde_json::from_slice(&bytes).expect("valid JSON");

    assert_eq!(v["openapi"], "3.1.0");
    assert!(v["paths"].is_object());
    assert!(v["paths"]["/api/v1/questions"]["get"].is_object());
    assert_eq!(
        v["components"]["securitySchemes"]["ApiKeyAuth"]["name"],
        "X-API-Key"
    );
    // The paging defaults a consumer needs are in the document, not just in code.
    let params = v["paths"]["/api/v1/questions"]["get"]["parameters"]
        .as_array()
        .expect("parameters");
    // utoipa cannot emit `default` on a query parameter, so the paging defaults
    // must be stated in the description — assert they are not silently lost.
    let find = |name: &str| {
        params
            .iter()
            .find(|p| p["name"] == name)
            .unwrap_or_else(|| panic!("{name} documented"))["description"]
            .as_str()
            .unwrap_or_default()
            .to_string()
    };
    assert!(
        find("per_page").contains("50"),
        "per_page default must be stated"
    );
    assert!(find("per_page").contains("200"), "the cap must be stated");
    assert!(find("page").contains('1'), "page default must be stated");
    assert!(
        find("include_explanation").contains("false"),
        "include_explanation default must be stated"
    );

    // A default, where one *is* emitted, must match its schema type.
    for p in params {
        let ty = &p["schema"]["type"];
        let def = &p["schema"]["default"];
        if !def.is_null() {
            let ok = match ty.as_str() {
                Some("integer") | Some("number") => def.is_number(),
                Some("boolean") => def.is_boolean(),
                _ => def.is_string(),
            };
            assert!(ok, "{}: default {def} does not match type {ty}", p["name"]);
        }
    }

    // Schemas are derived from the types the handlers actually return.
    let schemas = v["components"]["schemas"].as_object().expect("schemas");
    for required in [
        "QuestionPage",
        "RenderedQuestion",
        "Syllabus",
        "SyllabusSummary",
        "Subject",
        "Choice",
        "Explanation",
        "ApiKey",
    ] {
        assert!(schemas.contains_key(required), "missing schema: {required}");
    }
}
