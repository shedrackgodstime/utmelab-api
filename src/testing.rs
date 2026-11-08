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
    store::{
        sync::{BlockedReason, SyncPolicy, SyncStatus},
        ConnPool, SyncDb,
    },
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

/// Expire a minted access token behind the service's back, so a test can prove
/// the read path honors expiry without waiting out the clock.
pub(crate) async fn expire_token(s: &DbState, token: &str) {
    conn_of(s)
        .await
        .execute(
            "UPDATE api_access_tokens SET expires_at=?1 WHERE token_hash=?2",
            vec![
                turso::Value::Integer(crate::auth::session::now_unix() - 1),
                turso::Value::Text(crate::store::accounts::hash_key(token)),
            ],
        )
        .await
        .expect("expire token");
}

/// Revoke a key behind the service's back, so a test can prove its token
/// family dies on the next request.
pub(crate) async fn revoke_key(s: &DbState, prefix: &str) {
    conn_of(s)
        .await
        .execute(
            "UPDATE api_keys SET revoked=1 WHERE prefix=?1",
            vec![turso::Value::Text(prefix.to_string())],
        )
        .await
        .expect("revoke key");
}

/// The tables the API owns, at their production shape. Single-sourced from
/// [`crate::store::schema::DDL`], so a test cannot seed a shape the service
/// does not create.
pub(crate) async fn api_schema(conn: &turso::Connection) {
    for ddl in crate::store::schema::DDL {
        conn.execute(ddl, ()).await.expect("api schema");
    }
    for index in crate::store::schema::INDEXES {
        conn.execute(index, ()).await.expect("api index");
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
        "CREATE TABLE subjects (slug TEXT, exam TEXT, name TEXT, is_compulsory INTEGER, objective_paper_questions INTEGER, countries TEXT NOT NULL DEFAULT '[]', syllabus_exam TEXT, syllabus_subject TEXT)",
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

/// Seed one dashboard user and one signed-in session, keeping the engine
/// value types inside the store test boundary.
pub(crate) async fn issue_session(
    conn: &turso::Connection,
    user: &str,
    role: &str,
    token: &str,
    expires_at: i64,
) {
    conn.execute(
        "INSERT INTO dashboard_users (username, pw_hash, role) VALUES (?1, 'unused', ?2)",
        vec![
            turso::Value::Text(user.to_string()),
            turso::Value::Text(role.to_string()),
        ],
    )
    .await
    .expect("seed user");
    conn.execute(
        "INSERT INTO sessions (token_hash, username, expires_at) VALUES (?1, ?2, ?3)",
        vec![
            turso::Value::Text(crate::store::accounts::hash_key(token)),
            turso::Value::Text(user.to_string()),
            turso::Value::Integer(expires_at),
        ],
    )
    .await
    .expect("seed session");
}

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

/// Seed one bank exam and its subject offering. `syllabus` points the
/// offering at another board's syllabus when the catalog does that.
pub(crate) async fn seed_bank_exam(
    conn: &turso::Connection,
    exam: &str,
    subject: &str,
    syllabus: Option<(&str, &str)>,
) {
    conn.execute(
        "INSERT INTO exams VALUES (?1, ?1, '[\"NG\"]', 'live', 1, NULL, NULL, '[]')",
        vec![turso::Value::Text(exam.to_string())],
    )
    .await
    .expect("seed exam");
    let (syllabus_exam, syllabus_subject) = match syllabus {
        Some((exam, subject)) => (
            turso::Value::Text(exam.to_string()),
            turso::Value::Text(subject.to_string()),
        ),
        None => (turso::Value::Null, turso::Value::Null),
    };
    conn.execute(
        "INSERT INTO subjects VALUES (?1, ?2, ?1, 0, 40, '[]', ?3, ?4)",
        vec![
            turso::Value::Text(subject.to_string()),
            turso::Value::Text(exam.to_string()),
            syllabus_exam,
            syllabus_subject,
        ],
    )
    .await
    .expect("seed subject");
}

pub(crate) async fn seed_bank_topic(
    conn: &turso::Connection,
    exam: &str,
    subject: &str,
    topic: &str,
) {
    conn.execute(
        "INSERT INTO topics VALUES (?1, ?2, ?3, ?1, 1, 0, '[]', '[]')",
        vec![
            turso::Value::Text(topic.to_string()),
            turso::Value::Text(subject.to_string()),
            turso::Value::Text(exam.to_string()),
        ],
    )
    .await
    .expect("seed topic");
}

pub(crate) async fn seed_bank_subtopic(conn: &turso::Connection, topic: &str, subtopic: &str) {
    conn.execute(
        "INSERT INTO subtopics VALUES (?1, ?2, ?1, 1, '[]')",
        vec![
            turso::Value::Text(subtopic.to_string()),
            turso::Value::Text(topic.to_string()),
        ],
    )
    .await
    .expect("seed subtopic");
}

#[allow(clippy::too_many_arguments)]
pub(crate) async fn seed_note(
    conn: &turso::Connection,
    id: &str,
    exam: &str,
    subject: &str,
    topic_slug: &str,
    subtopic_slug: Option<&str>,
    key_takeaway: &str,
    sections: &str,
) {
    conn.execute(
        "INSERT INTO topic_notes (id, exam, subject, topic_slug, subtopic_slug, title, read_time_minutes, key_takeaway, sections, worked_examples, formulas, active_recall_checks, examiner_traps, linked_question_ids, content_hash) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, 3, ?7, ?8, '[]', '[]', '[]', '[]', '[]', 'hash')",
        vec![
            turso::Value::Text(id.to_string()),
            turso::Value::Text(exam.to_string()),
            turso::Value::Text(subject.to_string()),
            turso::Value::Text(topic_slug.to_string()),
            subtopic_slug
                .map(|slug| turso::Value::Text(slug.to_string()))
                .unwrap_or(turso::Value::Null),
            turso::Value::Text(format!("{id} title")),
            turso::Value::Text(key_takeaway.to_string()),
            turso::Value::Text(sections.to_string()),
        ],
    )
    .await
    .expect("seed note");
}

pub(crate) async fn seed_theory_question(conn: &turso::Connection, id: &str) {
    conn.execute(
        "INSERT INTO theory_questions (id, exam, subject, year, paper, section, question_number, topic_slug, subtopic_slug, total_marks, stem, diagram_url, sub_parts, formulation_bridge, marking_methods, diagram_rubric, penalties, examiner_report, content_hash) \
         VALUES (?1, 'WAEC', 'general-mathematics', 2023, 2, 'Section A', '4', 'algebra', null, 8, \
         '{\"text\":\"Garden problem\",\"inline\":[]}', 'diagrams/garden.png', \
         '[{\"part_label\":\"(a)\",\"prompt\":\"Form equation\",\"allocated_marks\":3},{\"part_label\":\"(b)\",\"prompt\":\"Solve equation\",\"allocated_marks\":5}]', \
         '[{\"clause\":\"Perimeter is 48\",\"variable_mapping\":\"2(L+B)=48\",\"derived_equation\":\"B=24-L\"}]', \
         '[{\"method_id\":\"m1\",\"method_name\":\"Method 1\",\"is_primary\":true,\"steps\":[\
            {\"step_id\":\"s1\",\"part_label\":\"(a)\",\"description\":\"Isolate B\",\"expression\":\"B=24-L\",\"mark_type\":\"M\",\"mark_value\":1,\"notes\":null},\
            {\"step_id\":\"s2\",\"part_label\":\"(a)\",\"description\":\"Form quadratic\",\"expression\":\"L^2-24L+135=0\",\"mark_type\":\"M\",\"mark_value\":1,\"notes\":null},\
            {\"step_id\":\"s3\",\"part_label\":\"(a)\",\"description\":\"Standard form\",\"expression\":\"L^2-24L+135=0\",\"mark_type\":\"A\",\"mark_value\":1,\"notes\":null},\
            {\"step_id\":\"s4\",\"part_label\":\"(b)\",\"description\":\"Factorize\",\"expression\":\"(L-15)(L-9)=0\",\"mark_type\":\"M\",\"mark_value\":2,\"notes\":null},\
            {\"step_id\":\"s5\",\"part_label\":\"(b)\",\"description\":\"Solve roots\",\"expression\":\"L=15 or 9\",\"mark_type\":\"A\",\"mark_value\":1,\"notes\":null},\
            {\"step_id\":\"s6\",\"part_label\":\"(b)\",\"description\":\"Dimensions with units\",\"expression\":\"15m and 9m\",\"mark_type\":\"A\",\"mark_value\":2,\"notes\":null}\
         ]} ]', \
         '{\"title_marks\":1,\"line_quality_marks\":1,\"proportion_marks\":1,\"label_marks\":1,\"guidelines\":[\"Use continuous lines\"]}', \
         '[{\"penalty_type\":\"unit_omission\",\"deduction\":1,\"description\":\"Missing metre unit\"},{\"penalty_type\":\"premature_rounding\",\"deduction\":1,\"description\":\"Early rounding\"}]', \
         '{\"general_performance\":\"Fair\",\"common_errors\":[\"Did not convert back to x\"],\"remedies\":\"Check final units\"}', \
         'hash_test')",
        vec![turso::Value::Text(id.to_string())],
    )
    .await
    .expect("insert theory question");
}

/// `DbState` over a replica.
pub(crate) fn db_state(db: SyncDb) -> DbState {
    DbState::detached(db)
}

/// `DbState` with no replica: a chosen readiness state and gate width, for
/// tests that never reach the store.
pub(crate) fn db_state_without_db(ready: bool, permits: usize) -> DbState {
    let policy = SyncPolicy::default();
    let sync = if ready {
        SyncStatus::verified(policy)
    } else {
        SyncStatus::blocked(policy, BlockedReason::SchemaMismatch)
    };
    DbState {
        sync: Arc::new(sync),
        db: Arc::new(tokio::sync::RwLock::new(None)),
        db_gate: Arc::new(tokio::sync::Semaphore::new(permits)),
        conns: Arc::new(ConnPool::new(permits)),
        metrics: Arc::new(Metrics::default()),
        cookie_secure: false,
        read_timeout_secs: crate::config::DEFAULT_READ_TIMEOUT_SECS,
        write_mutex: Arc::new(tokio::sync::Mutex::new(())),
        push_notify: Arc::new(tokio::sync::Notify::new()),
        pull_notify: Arc::new(tokio::sync::Notify::new()),
        limiter: Arc::new(RateLimiter::new()),
        bank_version: Arc::new(std::sync::RwLock::new(format!(
            "v{}",
            crate::store::schema::CONTRACT_VERSION
        ))),
        discovery_cache: Arc::new(tokio::sync::RwLock::new(None)),
        paper_metadata_cache: Arc::new(tokio::sync::RwLock::new(None)),
        media_base_url: Arc::from(crate::config::DEFAULT_MEDIA_BASE_URL),
    }
}

/// `AppState` over a replica, contract trusted.
pub(crate) fn state(db: SyncDb) -> AppState {
    app_from(db_state(db))
}

/// `AppState` with no replica and a chosen readiness state.
pub(crate) fn state_without_db(ready: bool) -> AppState {
    app_from(db_state_without_db(ready, 1))
}

/// The one place tests assemble an `AppState` from a `DbState`.
fn app_from(d: DbState) -> AppState {
    AppState {
        name: Arc::from("test"),
        sync: d.sync,
        db: d.db,
        db_gate: d.db_gate,
        conns: d.conns,
        metrics: d.metrics,
        cookie_secure: false,
        read_timeout_secs: d.read_timeout_secs,
        write_mutex: d.write_mutex,
        push_notify: d.push_notify,
        pull_notify: d.pull_notify,
        limiter: d.limiter,
        bank_version: d.bank_version,
        discovery_cache: d.discovery_cache,
        paper_metadata_cache: d.paper_metadata_cache,
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
    call_session_with_headers(app, method, uri, token, &[], body).await
}

pub(crate) async fn call_session_with_headers(
    app: axum::Router,
    method: &str,
    uri: &str,
    token: &str,
    extra: &[(&str, &str)],
    body: Option<&str>,
) -> (axum::http::StatusCode, serde_json::Value) {
    let cookie = format!("{}={token}", crate::auth::session::SESSION_COOKIE);
    let mut headers = vec![("cookie", cookie.as_str())];
    headers.extend_from_slice(extra);
    let (status, _, value) = drive(app, method, uri, &headers, body).await;
    (status, value)
}
