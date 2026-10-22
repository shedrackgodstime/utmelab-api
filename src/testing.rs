//! Test scaffolding, compiled only under `#[cfg(test)]`.
//!
//! One definition of the two things every fixture needs: an offline replica
//! and a minted key, plus the schema and the HTTP call. A test then declares
//! only the rows it is about, never the plumbing.
//!
//! The replica is a unique temp file with sync on and the remote pointed at a
//! port nothing listens on. `bootstrap_if_empty(false)` keeps `build()` off the
//! network, and a write still fails at `push()`: that failing push is the
//! boundary the store's write path can be exercised at, which is why seeding
//! goes through a raw connection.

use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, OnceLock,
};

use tower::ServiceExt;

use crate::{
    auth::rate_limit::RateLimiter,
    state::{AppState, DbState, Metrics},
    store::{ConnPool, SyncDb},
};

/// A path no other call in this process uses. The nonce is fixed per run, so a
/// recycled pid cannot collide with a file an earlier run left behind.
fn unique_path() -> std::path::PathBuf {
    static SEQ: AtomicU64 = AtomicU64::new(0);
    static NONCE: OnceLock<u64> = OnceLock::new();
    let nonce = *NONCE.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0)
    });
    let n = SEQ.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "utmelab-test-{}-{nonce}-{n}.db",
        std::process::id()
    ))
}

/// A fresh offline replica.
pub(crate) async fn replica() -> SyncDb {
    let path = unique_path();
    let db = turso::sync::Builder::new_remote(path.to_str().expect("tmp path"))
        .with_remote_url("http://127.0.0.1:9")
        .with_auth_token("test-only")
        .bootstrap_if_empty(false)
        .build()
        .await
        .expect("local sync db builds offline");
    Arc::new(db)
}

/// A raw connection for seeding, bypassing the pushing write path.
pub(crate) async fn connect(db: &SyncDb) -> turso::Connection {
    db.connect().await.expect("connect")
}

/// A raw connection over the replica behind `s`.
pub(crate) async fn conn_of(s: &DbState) -> turso::Connection {
    let db = s.db.read().await.clone().expect("db");
    connect(&db).await
}

/// The tables the API owns, at their production shape. Single-sourced from
/// [`crate::store::schema::DDL`], so a test cannot seed a shape the service
/// does not create.
pub(crate) async fn api_schema(conn: &turso::Connection) {
    for ddl in crate::store::schema::DDL {
        conn.execute(ddl, ()).await.expect("api schema");
    }
}

/// The bank tables named, at the shapes the readers depend on. The column list
/// comes from `READ_SHAPES`; the types live in [`BANK_DDL`] because SQLite
/// affinity decides what `get::<i64>()`/`get::<f64>()` return.
pub(crate) async fn bank_schema(conn: &turso::Connection, tables: &[&str]) {
    for name in tables {
        let ddl = BANK_DDL
            .iter()
            .find(|(t, _)| t == name)
            .unwrap_or_else(|| panic!("no test DDL for bank table {name}"))
            .1;
        conn.execute(ddl, ())
            .await
            .unwrap_or_else(|e| panic!("create {name}: {e}"));
    }
}

/// The bank table shapes, one per table a test reads, so a reader change is
/// one edit rather than one per fixture. Pipeline-owned: the API declares these
/// as reads in `store::schema::READ_SHAPES` and never creates them.
const BANK_DDL: &[(&str, &str)] = &[
    (
        "exams",
        "CREATE TABLE exams (code TEXT, name TEXT, countries TEXT, status TEXT, has_full_paper INTEGER, subjects_required INTEGER, duration_minutes INTEGER, rules TEXT)",
    ),
    (
        "exam_requirements",
        "CREATE TABLE exam_requirements (exam TEXT, country TEXT, \"group\" TEXT, min_select INTEGER, subjects TEXT)",
    ),
    (
        "subjects",
        "CREATE TABLE subjects (slug TEXT, exam TEXT, name TEXT, is_compulsory INTEGER, objective_paper_questions INTEGER)",
    ),
    (
        "topics",
        "CREATE TABLE topics (slug TEXT, subject TEXT, exam TEXT, name TEXT, \"order\" INTEGER, weight INTEGER, objectives TEXT, countries TEXT NOT NULL DEFAULT '[]')",
    ),
    (
        "subtopics",
        "CREATE TABLE subtopics (slug TEXT, topic TEXT, name TEXT, \"order\" INTEGER, objectives TEXT)",
    ),
    (
        "questions",
        "CREATE TABLE questions (id TEXT, exam TEXT, subject TEXT, year INTEGER, source TEXT, text TEXT, inline TEXT, options TEXT, answer TEXT, subtopic_id TEXT, section TEXT, passage_id TEXT, explanation TEXT, marks REAL, difficulty INTEGER, content_hash TEXT)",
    ),
    (
        "verifications",
        "CREATE TABLE verifications (id TEXT, question_id TEXT, kind TEXT, verdict TEXT, scope TEXT, verifier TEXT, detail TEXT, content_hash TEXT, created_at TEXT)",
    ),
    (
        "passages",
        "CREATE TABLE passages (id TEXT, exam TEXT, subject TEXT, year INTEGER, kind TEXT, title TEXT, author TEXT, text TEXT, inline TEXT)",
    ),
    (
        "novels",
        "CREATE TABLE novels (id TEXT, title TEXT, author TEXT, year_published INTEGER, exam TEXT, year_prescribed TEXT, category TEXT, featured INTEGER, synopsis TEXT, setting_place TEXT, setting_period TEXT, cover_image TEXT)",
    ),
    (
        "novel_chapters",
        "CREATE TABLE novel_chapters (novel_id TEXT, number INTEGER, title TEXT, summary TEXT, key_events TEXT)",
    ),
    (
        "novel_characters",
        "CREATE TABLE novel_characters (novel_id TEXT, name TEXT, role TEXT, character_type TEXT, description TEXT)",
    ),
    (
        "novel_themes",
        "CREATE TABLE novel_themes (novel_id TEXT, name TEXT, description TEXT, evidence TEXT)",
    ),
    (
        "novel_questions",
        "CREATE TABLE novel_questions (id TEXT, novel_id TEXT, chapter_number INTEGER, text TEXT, inline TEXT, options TEXT, answer TEXT, explanation TEXT, content_hash TEXT)",
    ),
    (
        "blueprints",
        "CREATE TABLE blueprints (exam TEXT, subject TEXT, level TEXT, topic TEXT, section TEXT, members TEXT, paper_size INTEGER, pct REAL, pct_low REAL, pct_high REAL, expected REAL, expected_low REAL, expected_high REAL, source TEXT, sample TEXT, method TEXT, confidence TEXT, status TEXT, note TEXT)",
    ),
];

/// Mint a key. `full` is the whole credential (`prefix.secret`); the table
/// stores only the prefix and its hash. Returns `full`, so a test presents
/// exactly what it seeded.
pub(crate) async fn issue_key(
    conn: &turso::Connection,
    full: &str,
    tier: &str,
    scopes: &str,
    revoked: bool,
) -> String {
    let (prefix, _) = full.split_once('.').expect("key shape is prefix.secret");
    conn.execute(
        "INSERT INTO api_keys (prefix, hash, tier, scopes, revoked, owner) VALUES (?1, ?2, ?3, ?4, ?5, '')",
        vec![
            turso::Value::Text(prefix.to_string()),
            turso::Value::Text(crate::store::accounts::hash_key(full)),
            turso::Value::Text(tier.to_string()),
            turso::Value::Text(scopes.to_string()),
            turso::Value::Integer(revoked as i64),
        ],
    )
    .await
    .expect("insert key");
    full.to_string()
}

/// `DbState` over a replica.
pub(crate) fn db_state(db: SyncDb) -> DbState {
    DbState::detached(db)
}

/// `DbState` with no replica: a chosen contract flag and gate width, for tests
/// that never reach the store.
pub(crate) fn db_state_without_db(contract_ok: bool, permits: usize) -> DbState {
    DbState {
        db: Arc::new(tokio::sync::RwLock::new(None)),
        db_gate: Arc::new(tokio::sync::Semaphore::new(permits)),
        conns: Arc::new(ConnPool::new(permits)),
        metrics: Arc::new(Metrics::default()),
        cookie_secure: false,
        write_mutex: Arc::new(tokio::sync::Mutex::new(())),
        contract_ok: Arc::new(std::sync::atomic::AtomicBool::new(contract_ok)),
        limiter: Arc::new(RateLimiter::new()),
        bank_version: Arc::new(std::sync::RwLock::new(format!(
            "v{}",
            crate::store::schema::CONTRACT_VERSION
        ))),
        media_base_url: Arc::from(crate::config::DEFAULT_MEDIA_BASE_URL),
    }
}

/// `AppState` over a replica, contract trusted.
pub(crate) fn state(db: SyncDb) -> AppState {
    app_from(db_state(db))
}

/// `AppState` with no replica and a chosen contract flag.
pub(crate) fn state_without_db(contract_ok: bool) -> AppState {
    app_from(db_state_without_db(contract_ok, 1))
}

/// The one place tests assemble an `AppState` from a `DbState`.
fn app_from(d: DbState) -> AppState {
    AppState {
        name: Arc::from("test"),
        db: d.db,
        db_gate: d.db_gate,
        conns: d.conns,
        metrics: d.metrics,
        cookie_secure: false,
        write_mutex: d.write_mutex,
        contract_ok: d.contract_ok,
        limiter: d.limiter,
        bank_version: d.bank_version,
        media_base_url: d.media_base_url,
    }
}

/// Drive the real router with one request and the given headers. Returns the
/// status, the response headers, and the parsed JSON body (`Value::Null` when
/// there is none). Headers come back because some of them are a contract too:
/// a cache directive, an ETag, a `Retry-After`.
async fn drive(
    app: axum::Router,
    method: &str,
    uri: &str,
    headers: &[(&str, &str)],
    body: Option<&str>,
) -> (
    axum::http::StatusCode,
    axum::http::HeaderMap,
    serde_json::Value,
) {
    let mut req = axum::http::Request::builder().method(method).uri(uri);
    for (name, value) in headers {
        req = req.header(*name, *value);
    }
    let req = match body {
        Some(b) => req
            .header("content-type", "application/json")
            .body(axum::body::Body::from(b.to_string())),
        None => req.body(axum::body::Body::empty()),
    }
    .expect("request");
    let res = app.oneshot(req).await.expect("call");
    let status = res.status();
    let head = res.headers().clone();
    let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
        .await
        .expect("body");
    let value = serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null);
    (status, head, value)
}

/// Drive the router as an API-key caller.
pub(crate) async fn call(
    app: axum::Router,
    method: &str,
    uri: &str,
    key: Option<&str>,
    body: Option<&str>,
) -> (axum::http::StatusCode, serde_json::Value) {
    let (status, _, value) = call_with_headers(app, method, uri, key, &[], body).await;
    (status, value)
}

/// [`call`], with the response headers kept and extra request headers allowed
/// (`if-none-match` for a conditional read, for instance).
pub(crate) async fn call_with_headers(
    app: axum::Router,
    method: &str,
    uri: &str,
    key: Option<&str>,
    extra: &[(&str, &str)],
    body: Option<&str>,
) -> (
    axum::http::StatusCode,
    axum::http::HeaderMap,
    serde_json::Value,
) {
    let mut headers: Vec<(&str, &str)> = Vec::new();
    if let Some(k) = key {
        headers.push(("x-api-key", k));
    }
    headers.extend_from_slice(extra);
    drive(app, method, uri, &headers, body).await
}

/// Drive the router as a signed-in dashboard session. `token` is the raw
/// cookie value; the store keeps only its hash.
pub(crate) async fn call_session(
    app: axum::Router,
    method: &str,
    uri: &str,
    token: &str,
    body: Option<&str>,
) -> (axum::http::StatusCode, serde_json::Value) {
    let cookie = format!("{}={token}", crate::auth::session::SESSION_COOKIE);
    let (status, _, value) = drive(app, method, uri, &[("cookie", cookie.as_str())], body).await;
    (status, value)
}
