//! Composition root: merges the surfaces plus `/health` (liveness) and
//! `/ready` (readiness) and applies the global layers. Surface-specific
//! layers live with their surface; only transport-agnostic limits live here.
//! Time budgets come from `Config` so surfaces never import each other for
//! them.
//!
//! URL policy: `/api/*` (v1 commercial reads, internal dashboard/admin)
//! nests here so local and prod paths are identical, with no proxy prefix
//! magic. `/mcp/*`, `/health` and `/ready` stay top-level. Data surfaces sit
//! behind the contract guard; the two probes do not.

pub mod health;

use axum::{
    body::Body,
    extract::State,
    http::Request,
    middleware::Next,
    response::{IntoResponse, Response},
    routing::get,
    Router,
};
use tower::limit::ConcurrencyLimitLayer;
use tower_http::{
    catch_panic::CatchPanicLayer,
    request_id::{MakeRequestUuid, PropagateRequestIdLayer, SetRequestIdLayer},
    trace::{DefaultOnFailure, TraceLayer},
};
use tracing::Level;

use crate::{api, config::Config, error::AppError, internal, mcp, state::AppState};

const REQUEST_ID: &str = "x-request-id";

async fn not_found() -> AppError {
    AppError::NotFound
}

/// Fail closed while the sync task reports a schema contract mismatch. The
/// replica's shape is then not the one this build reads, so answering would
/// mean serving rows we cannot trust; the log already says "refusing to trust
/// replica", and this is what makes that true. `/health` stays outside the
/// guard so liveness is independent of the database.
async fn contract_guard(
    State(state): State<AppState>,
    request: Request<Body>,
    next: Next,
) -> Response {
    if !state.contract_ok.load(std::sync::atomic::Ordering::Relaxed) {
        return AppError::SchemaMismatch.into_response();
    }
    next.run(request).await
}

/// Latency bucket edges in milliseconds for request telemetry.
const FAST_MS: u64 = 25;
const OK_MS: u64 = 100;

/// Request telemetry: status-class counts, an in-flight gauge, and three
/// latency buckets. Atomics only, so it costs a few increments per request and
/// nothing while idle. Outermost layer, so it times what a client actually
/// waits for; the two probes are skipped so health checks cannot drown out
/// real traffic.
async fn telemetry(State(state): State<AppState>, request: Request<Body>, next: Next) -> Response {
    use std::sync::atomic::Ordering::Relaxed;

    if matches!(request.uri().path(), "/health" | "/ready") {
        return next.run(request).await;
    }
    let m = &state.metrics;
    m.in_flight.fetch_add(1, Relaxed);
    let started = std::time::Instant::now();
    let response = next.run(request).await;
    m.in_flight.fetch_sub(1, Relaxed);

    let status = response.status().as_u16();
    // 408 is our own timeout: a capacity signal, not a client mistake.
    if status >= 500 || status == 408 {
        m.requests_server_error.fetch_add(1, Relaxed);
    } else if status >= 400 {
        m.requests_client_error.fetch_add(1, Relaxed);
    } else {
        m.requests_ok.fetch_add(1, Relaxed);
    }
    let ms = started.elapsed().as_millis() as u64;
    let bucket = if ms < FAST_MS {
        &m.latency_fast
    } else if ms < OK_MS {
        &m.latency_ok
    } else {
        &m.latency_slow
    };
    bucket.fetch_add(1, Relaxed);
    response
}

fn span_for(request: &Request<Body>) -> tracing::Span {
    let id = request
        .headers()
        .get(REQUEST_ID)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("none")
        .to_string();
    tracing::info_span!("request", id, method = %request.method(), path = %request.uri().path())
}

pub fn router(state: AppState, cfg: &Config) -> Router {
    let api = Router::new()
        .merge(api::router(state.clone(), cfg))
        .merge(internal::router(state.clone(), cfg));
    // Every data surface sits behind the contract guard; only `/health`
    // stays public, and it carries no database.
    let gated = Router::new()
        .nest("/api", api)
        .merge(mcp::router(state.clone(), cfg))
        .layer(axum::middleware::from_fn_with_state(
            state.clone(),
            contract_guard,
        ));
    let telemetry_state = state.clone();
    Router::new()
        .route(
            "/health",
            get(health::health).route_layer(cfg.fast_timeout()),
        )
        .route("/ready", get(health::ready).route_layer(cfg.fast_timeout()))
        .merge(gated)
        .fallback(not_found)
        .with_state(state)
        .layer((
            // Innermost, so the 500 it synthesises still passes back through
            // request-id, trace, and telemetry: a handler panic is logged and
            // counted instead of resetting the client connection.
            CatchPanicLayer::new(),
            SetRequestIdLayer::new(
                axum::http::HeaderName::from_static(REQUEST_ID),
                MakeRequestUuid,
            ),
            TraceLayer::new_for_http()
                .make_span_with(span_for)
                .on_failure(DefaultOnFailure::new().level(Level::WARN)),
            PropagateRequestIdLayer::new(axum::http::HeaderName::from_static(REQUEST_ID)),
            // 16 KiB is ~5x our largest body (a 40-answer paper score). A
            // JSON bomb dies at the edge, not in serde.
            axum::extract::DefaultBodyLimit::max(16 * 1024),
            ConcurrencyLimitLayer::new(cfg.concurrency_limit),
            // Outermost timeout by construction, so it is the net every route
            // falls back on: a route that forgets its own budget still cannot
            // run forever and hold a DB permit. Read routes layer 5s inside
            // this. Telemetry sits above it and only observes.
            cfg.slow_timeout(),
        ))
        .layer(axum::middleware::from_fn_with_state(
            telemetry_state,
            telemetry,
        ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::{
        api_schema, bank_schema, call, call_with_headers, connect, db_state_without_db, issue_key,
        replica, state, state_without_db,
    };
    use std::sync::Arc;
    use tower::ServiceExt;

    /// The composed app over a contract flag, no replica behind it: the layer
    /// stack and the router tables, nothing that reads a store.
    fn app(contract_ok: bool) -> Router {
        crate::routes::router(
            state_without_db(contract_ok),
            &crate::config::Config::default(),
        )
    }

    /// The raw body out, for the guard test: a non-JSON handler body must not
    /// leak past the guard, which a parsed value could not show.
    async fn probe(contract_ok: bool) -> (axum::http::StatusCode, String) {
        let app = Router::new()
            .route("/data", get(|| async { "payload" }))
            .layer(axum::middleware::from_fn_with_state(
                state_without_db(contract_ok),
                contract_guard,
            ));
        let res = app
            .oneshot(
                Request::builder()
                    .uri("/data")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("router call");
        let status = res.status();
        let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
            .await
            .expect("body");
        (status, String::from_utf8(bytes.to_vec()).expect("utf8"))
    }

    #[tokio::test]
    async fn contract_guard_fails_closed_on_mismatch() {
        let (status, body) = probe(false).await;
        assert_eq!(status, axum::http::StatusCode::SERVICE_UNAVAILABLE);
        assert!(body.contains("schema_mismatch"), "{body}");
        assert!(!body.contains("payload"), "body leaked past the guard");
    }

    #[tokio::test]
    async fn contract_guard_passes_when_trusted() {
        let (status, body) = probe(true).await;
        assert_eq!(status, axum::http::StatusCode::OK);
        assert_eq!(body, "payload");
    }

    #[tokio::test]
    async fn ready_is_503_until_a_replica_exists() {
        let err = health::ready(State(db_state_without_db(true, 1)))
            .await
            .expect_err("no replica yet");
        assert!(matches!(err, AppError::DbUnavailable(_)));
    }

    #[tokio::test]
    async fn router_wires_guard_and_telemetry() {
        let st = state_without_db(true);
        let metrics = Arc::clone(&st.metrics);
        let app = crate::routes::router(st, &crate::config::Config::default());

        assert_eq!(
            call(app.clone(), "GET", "/health", None, None).await.0,
            axum::http::StatusCode::OK
        );
        assert_eq!(
            call(app.clone(), "GET", "/api/v1/meta/tables", None, None)
                .await
                .0,
            axum::http::StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            call(app, "GET", "/ready", None, None).await.0,
            axum::http::StatusCode::SERVICE_UNAVAILABLE
        );

        let snap = metrics.snapshot();
        assert_eq!(snap.requests_client_error, 1, "the 401 is counted once");
        assert_eq!(snap.requests_ok, 0, "neither probe is counted");
        assert_eq!(snap.in_flight, 0);
        assert_eq!(snap.latency_fast + snap.latency_ok + snap.latency_slow, 1);
    }

    #[tokio::test]
    async fn router_fails_closed_through_the_guard() {
        let app = app(false);
        assert_eq!(
            call(app.clone(), "GET", "/api/v1/meta/tables", None, None)
                .await
                .0,
            axum::http::StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            call(app, "GET", "/health", None, None).await.0,
            axum::http::StatusCode::OK
        );
    }

    #[tokio::test]
    async fn admin_surface_lives_under_admin() {
        let app = app(true);
        assert_eq!(
            call(app.clone(), "GET", "/api/internal/admin/status", None, None)
                .await
                .0,
            axum::http::StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            call(app, "GET", "/api/internal/status", None, None).await.0,
            axum::http::StatusCode::NOT_FOUND
        );
    }

    #[tokio::test]
    async fn report_write_routes_stay_wired_outside_the_read_group() {
        // `reports` sits outside the read-timeout group in `api::router`, so
        // this guards against the move dropping the routes to a 404.
        let app = app(true);
        assert_eq!(
            call(app.clone(), "POST", "/api/v1/report", None, None)
                .await
                .0,
            axum::http::StatusCode::UNAUTHORIZED
        );
    }

    fn boom() {
        panic!("boom");
    }

    #[tokio::test]
    async fn a_handler_panic_becomes_a_500() {
        // Integration of the innermost catch-panic layer with our Body type:
        // a panic must surface as 500, not a dropped connection.
        let app: Router = Router::new()
            .route("/boom", get(|| async { boom() }))
            .layer(CatchPanicLayer::new());
        assert_eq!(
            call(app, "GET", "/boom", None, None).await.0,
            axum::http::StatusCode::INTERNAL_SERVER_ERROR
        );
    }

    /// Every documented `/api/v1` route: method, OpenAPI template, and a
    /// concrete probe. The template is what the spec advertises; the probe is
    /// what the identity sweeps call; the read templates are what the MCP
    /// resources mirror. One list, so a route cannot be mounted but
    /// undocumented, or documented but unmounted.
    const API_ROUTES: &[(&str, &str, &str)] = &[
        ("GET", "/api/v1/exams", "/api/v1/exams"),
        (
            "GET",
            "/api/v1/exams/{exam}/subjects",
            "/api/v1/exams/JAMB/subjects",
        ),
        (
            "GET",
            "/api/v1/exams/{exam}/papers",
            "/api/v1/exams/JAMB/papers",
        ),
        (
            "GET",
            "/api/v1/subjects/{exam}/{slug}",
            "/api/v1/subjects/JAMB/physics",
        ),
        (
            "GET",
            "/api/v1/subjects/{exam}/{slug}/syllabus",
            "/api/v1/subjects/JAMB/physics/syllabus",
        ),
        (
            "GET",
            "/api/v1/subjects/{exam}/{slug}/coverage",
            "/api/v1/subjects/JAMB/physics/coverage",
        ),
        (
            "GET",
            "/api/v1/topics/{exam}/{subject}/{slug}",
            "/api/v1/topics/JAMB/physics/mechanics",
        ),
        (
            "GET",
            "/api/v1/blueprints/{exam}/{subject}",
            "/api/v1/blueprints/JAMB/physics",
        ),
        ("GET", "/api/v1/passages", "/api/v1/passages?ids=p1"),
        ("GET", "/api/v1/passages/{id}", "/api/v1/passages/p1"),
        ("GET", "/api/v1/novels", "/api/v1/novels"),
        ("GET", "/api/v1/novels/{id}", "/api/v1/novels/lekki"),
        (
            "GET",
            "/api/v1/novels/{id}/questions",
            "/api/v1/novels/lekki/questions",
        ),
        ("GET", "/api/v1/questions", "/api/v1/questions"),
        (
            "GET",
            "/api/v1/questions/sample",
            "/api/v1/questions/sample?exam=JAMB&subject=physics",
        ),
        ("GET", "/api/v1/questions/{id}", "/api/v1/questions/q1"),
        ("GET", "/api/v1/keys/me", "/api/v1/keys/me"),
        ("GET", "/api/v1/meta/tables", "/api/v1/meta/tables"),
        (
            "GET",
            "/api/v1/meta/rows/{table}",
            "/api/v1/meta/rows/exams",
        ),
        ("POST", "/api/v1/report", "/api/v1/report"),
        (
            "POST",
            "/api/v1/papers/{exam}/{subject}",
            "/api/v1/papers/JAMB/physics",
        ),
        (
            "POST",
            "/api/v1/papers/{exam}/{subject}/score",
            "/api/v1/papers/JAMB/physics/score",
        ),
    ];

    /// The keyless discovery routes, in a list of their own for one reason:
    /// `API_ROUTES` is swept for a *missing key* refusal, and these must do the
    /// opposite. Listing them here is what makes "answers without a key" a
    /// deliberate entry rather than an omission, and the sweeps below prove
    /// both halves of the divide.
    const PUBLIC_ROUTES: &[(&str, &str, &str)] = &[
        ("GET", "/api/v1/public/summary", "/api/v1/public/summary"),
        ("GET", "/api/v1/public/exams", "/api/v1/public/exams"),
        (
            "GET",
            "/api/v1/public/syllabus/{exam}/{slug}",
            "/api/v1/public/syllabus/JAMB/use-of-english",
        ),
    ];

    /// The MCP surface is gated endpoints, one per capability set. Its tools
    /// and resources are covered in the `mcp` module's own tests, where the
    /// JSON-RPC envelope is available; here they only have to answer the same
    /// 401/revocation sweep as every other keyed route.
    const MCP_ENDPOINT: &[(&str, &str)] = &[("POST", "/mcp"), ("POST", "/mcp/admin")];

    /// Every keyed route: the documented `/api/v1` routes plus `/mcp`.
    fn keyed_routes() -> Vec<(String, String)> {
        API_ROUTES
            .iter()
            .map(|(m, _, probe)| (m.to_string(), probe.to_string()))
            .chain(
                MCP_ENDPOINT
                    .iter()
                    .map(|(m, u)| (m.to_string(), u.to_string())),
            )
            .collect()
    }

    /// The mirror is asserted, not retyped: the MCP surface exposes exactly one
    /// resource or template per HTTP read. A concrete read (no `{`) must be a
    /// fixed resource; a parameterised one must be a template. Set equality both
    /// ways, so adding a read to `api/v1` without its resource fails, and a
    /// resource with no route behind it fails too. Behavioural parity (a
    /// resource's answer equals its route's) is proved in the `mcp` tests, where
    /// the JSON-RPC envelope is available.
    #[test]
    fn every_http_read_has_one_mcp_resource() {
        let tails: Vec<&str> = API_ROUTES
            .iter()
            .filter(|(method, _, _)| *method == "GET")
            .map(|(_, template, _)| template.strip_prefix("/api/v1/").expect("an api/v1 path"))
            .collect();
        let fixed: Vec<String> = crate::mcp::resources::list()
            .iter()
            .map(|r| {
                r.uri
                    .strip_prefix("utmelab://catalog/")
                    .expect("a catalog uri")
                    .to_string()
            })
            .collect();
        let templates: Vec<String> = crate::mcp::resources::templates()
            .iter()
            .map(|t| {
                t.uri_template
                    .strip_prefix("utmelab://catalog/")
                    .expect("a catalog uri template")
                    .to_string()
            })
            .collect();
        let (concrete, parameterised): (Vec<&str>, Vec<&str>) =
            tails.iter().partition(|tail| !tail.contains('{'));
        let sorted = |xs: &[String]| {
            let mut xs = xs.to_vec();
            xs.sort();
            xs
        };
        assert_eq!(
            sorted(&concrete.iter().map(|s| s.to_string()).collect::<Vec<_>>()),
            sorted(&fixed),
            "every parameterless /api/v1 read needs exactly one MCP resource"
        );
        assert_eq!(
            sorted(
                &parameterised
                    .iter()
                    .map(|s| s.to_string())
                    .collect::<Vec<_>>()
            ),
            sorted(&templates),
            "every parameterised /api/v1 read needs exactly one MCP resource template"
        );
    }

    /// The spec is derived from the handlers, but its route list must equal this
    /// inventory (the keyed routes plus the keyless ones): a route mounted here
    /// and absent from the spec fails, and a path the spec advertises with no
    /// route behind it fails. With the identity sweep (which proves each probe
    /// is mounted and gated) and the security sweep (which proves the spec
    /// agrees about *which* routes are keyless), this closes the loop between
    /// the router, the spec, and the MCP mirror.
    #[test]
    fn the_spec_covers_exactly_the_api_routes() {
        let doc =
            serde_json::to_value(crate::api::openapi::document()).expect("the document serialises");
        let mut documented: Vec<(String, String)> = doc["paths"]
            .as_object()
            .expect("a paths object")
            .iter()
            .flat_map(|(path, item)| {
                item.as_object()
                    .expect("path item")
                    .keys()
                    .map(|method| (method.to_uppercase(), path.clone()))
            })
            .collect();
        let mut routed: Vec<(String, String)> = API_ROUTES
            .iter()
            .chain(PUBLIC_ROUTES.iter())
            .map(|(method, template, _)| (method.to_string(), template.to_string()))
            .collect();
        documented.sort();
        routed.sort();
        assert_eq!(
            documented, routed,
            "the OpenAPI document and the route inventory disagree"
        );
    }

    /// Session routes: the same rule through the cookie door. `login` is absent
    /// on purpose: it is how a session is obtained, so it cannot require one.
    /// `logout` is absent because it takes no session and always succeeds.
    const SESSION: &[(&str, &str)] = &[
        ("GET", "/api/internal/keys"),
        ("POST", "/api/internal/keys/create"),
        ("POST", "/api/internal/keys/delete"),
        ("GET", "/api/internal/admin/status"),
        ("GET", "/api/internal/admin/users"),
        ("POST", "/api/internal/admin/users/role"),
        ("GET", "/api/internal/admin/keys"),
        ("POST", "/api/internal/admin/keys/create"),
        ("POST", "/api/internal/admin/keys/revoke"),
        ("POST", "/api/internal/admin/keys/unrevoke"),
        ("GET", "/api/internal/admin/reports"),
    ];

    async fn assert_all_require_identity(routes: &[(String, String)]) {
        let app = app(true);
        for (method, uri) in routes {
            assert_eq!(
                call(app.clone(), method, uri, None, None).await.0,
                axum::http::StatusCode::UNAUTHORIZED,
                "{method} {uri} must require identity"
            );
        }
    }

    #[tokio::test]
    async fn every_keyed_route_rejects_a_missing_key() {
        assert_all_require_identity(&keyed_routes()).await;
    }

    #[tokio::test]
    async fn every_session_route_rejects_a_missing_cookie() {
        let routes: Vec<(String, String)> = SESSION
            .iter()
            .map(|(m, u)| (m.to_string(), u.to_string()))
            .collect();
        assert_all_require_identity(&routes).await;
    }

    /// Offline replica carrying the API's own tables. The key extractor reads
    /// `api_keys` before any handler runs, so a key's fate is settled here
    /// without seeding a bank.
    async fn keyed_app() -> Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        issue_key(&conn, "live.secret", "commercial", "read:catalog", false).await;
        issue_key(&conn, "revoked.secret", "commercial", "read:catalog", true).await;
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    #[tokio::test]
    async fn every_keyed_route_rejects_a_revoked_key() {
        let app = keyed_app().await;
        for (method, uri) in keyed_routes() {
            assert_eq!(
                call(app.clone(), &method, &uri, Some("revoked.secret"), None)
                    .await
                    .0,
                axum::http::StatusCode::UNAUTHORIZED,
                "{method} {uri} must refuse a revoked key"
            );
        }
        // The seed's live key is accepted, so the refusals above are the
        // revocation and not a malformed key. `/keys/me` reads no bank, so it
        // is the one route a bare `api_keys` table can answer.
        assert_eq!(
            call(
                app.clone(),
                "GET",
                "/api/v1/keys/me",
                Some("live.secret"),
                None
            )
            .await
            .0,
            axum::http::StatusCode::OK
        );
        // Identity is not authorization: the same live read key is refused at
        // the mcp admin tools, which need `manage:keys` (see the `mcp` tests).
        // The scope gate holds on that surface too.
    }

    /// A replica carrying the API's own tables plus the bank tables the
    /// discovery surface reads, with one exam and one subject seeded. Enough
    /// for the keyless payload to be a real answer rather than an empty one.
    async fn discovery_app() -> Router {
        let db = replica().await;
        let conn = connect(&db).await;
        api_schema(&conn).await;
        bank_schema(
            &conn,
            &[
                "exams",
                "subjects",
                "questions",
                "verifications",
                "topics",
                "subtopics",
            ],
        )
        .await;
        conn.execute(
            "INSERT INTO exams VALUES ('JAMB','Joint Admissions','[\"NG\"]','live',1,4,120,'[]')",
            (),
        )
        .await
        .expect("insert exam");
        conn.execute(
            "INSERT INTO subjects VALUES ('use-of-english','JAMB','Use of English',1,60,'[]',NULL,NULL)",
            (),
        )
        .await
        .expect("insert subject");
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    /// The other half of the divide the identity sweeps prove. A discovery
    /// route that starts refusing anonymous callers (a stray gate, a mount
    /// inside `v1::router`) fails here, and the funnel goes dark rather than
    /// going unnoticed.
    #[tokio::test]
    async fn every_public_route_answers_without_a_key() {
        let app = discovery_app().await;
        for &(method, _, probe) in PUBLIC_ROUTES {
            assert_eq!(
                call(app.clone(), method, probe, None, None).await.0,
                axum::http::StatusCode::OK,
                "{method} {probe} must answer an anonymous caller"
            );
        }
    }

    /// The public surface is cacheable and the keyed surface is not. The
    /// directive is what stops an anonymous funnel from costing a read per
    /// page view, and it is scoped to the discovery router, so a keyed answer
    /// can never be handed out by a shared cache. A `304` carries it too:
    /// revalidation is exactly when the browser needs to be told it may keep
    /// holding what it has.
    #[tokio::test]
    async fn the_discovery_surface_is_cacheable_and_the_keyed_surface_is_not() {
        let app = discovery_app().await;
        let (status, head, _) =
            call_with_headers(app.clone(), "GET", "/api/v1/public/exams", None, &[], None).await;
        assert_eq!(status, axum::http::StatusCode::OK);
        assert_eq!(
            head.get(axum::http::header::CACHE_CONTROL)
                .and_then(|value| value.to_str().ok()),
            Some(crate::api::middleware::PUBLIC_CACHE_CONTROL)
        );

        let etag = head
            .get(axum::http::header::ETAG)
            .and_then(|value| value.to_str().ok())
            .expect("the public read carries an ETag")
            .to_string();
        let (status, head, _) = call_with_headers(
            app.clone(),
            "GET",
            "/api/v1/public/exams",
            None,
            &[("if-none-match", etag.as_str())],
            None,
        )
        .await;
        assert_eq!(status, axum::http::StatusCode::NOT_MODIFIED);
        assert_eq!(
            head.get(axum::http::header::CACHE_CONTROL)
                .and_then(|value| value.to_str().ok()),
            Some(crate::api::middleware::PUBLIC_CACHE_CONTROL)
        );

        let (status, head, _) =
            call_with_headers(app, "GET", "/api/v1/exams", None, &[], None).await;
        assert_eq!(status, axum::http::StatusCode::UNAUTHORIZED);
        assert!(
            head.get(axum::http::header::CACHE_CONTROL).is_none(),
            "a keyed answer must not carry a shared-cache directive"
        );
    }

    /// The ceiling buckets on the entry our proxy attested, not on whatever the
    /// caller claimed. Rotating the leading entries must not buy a fresh
    /// bucket, which is exactly how this was defeatable; a different attested
    /// address must get its own.
    #[tokio::test]
    async fn the_keyless_ceiling_buckets_on_the_attested_address_not_a_claimed_one() {
        let app = discovery_app().await;
        let mut last = None;
        for i in 0..130 {
            let claimed = format!("10.0.0.{i}, 203.0.113.7");
            let (status, _, _) = call_with_headers(
                app.clone(),
                "GET",
                "/api/v1/public/summary",
                None,
                &[("x-forwarded-for", claimed.as_str())],
                None,
            )
            .await;
            last = Some(status);
        }
        assert_eq!(
            last,
            Some(axum::http::StatusCode::TOO_MANY_REQUESTS),
            "rotating the caller-supplied entry must not escape the ceiling"
        );

        let (status, _, _) = call_with_headers(
            app,
            "GET",
            "/api/v1/public/summary",
            None,
            &[("x-forwarded-for", "10.0.0.1, 198.51.100.9")],
            None,
        )
        .await;
        assert_eq!(
            status,
            axum::http::StatusCode::OK,
            "a different attested address is a different caller"
        );
    }

    /// The published contract has to agree about which routes are keyless. The
    /// scheme is declared once at the document root, so a keyed operation must
    /// not carry an override and a public one must carry the empty requirement
    /// that lifts the root. A route that changes sides without a spec change
    /// fails here, which is the only way a consumer learns the truth without
    /// reading our source.
    #[test]
    fn the_spec_says_exactly_which_routes_are_keyless() {
        let doc =
            serde_json::to_value(crate::api::openapi::document()).expect("the document serialises");
        assert_eq!(
            doc.get("security"),
            Some(&serde_json::json!([{ "ApiKeyAuth": [] }])),
            "the document root must still require the key scheme"
        );
        let item = |path: &str| doc.get("paths").and_then(|paths| paths.get(path));
        let op = |method: &str, path: &str| {
            item(path)
                .unwrap_or_else(|| panic!("{path} is not documented"))
                .get(method.to_lowercase())
                .unwrap_or_else(|| panic!("{method} {path} is not documented"))
        };
        let keyless = |op: &serde_json::Value| {
            op.get("security")
                .and_then(serde_json::Value::as_array)
                .is_some_and(|reqs| {
                    reqs.iter()
                        .all(|r| r.as_object().is_some_and(|o| o.is_empty()))
                })
        };

        for &(method, path, _) in PUBLIC_ROUTES {
            assert!(
                keyless(op(method, path)),
                "{method} {path} is keyless and must declare no security requirement"
            );
        }
        for &(method, path, _) in API_ROUTES {
            assert!(
                op(method, path).get("security").is_none(),
                "{method} {path} is keyed and must inherit the document's requirement"
            );
        }
    }
}
