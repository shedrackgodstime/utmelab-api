//! Phase 4 draft seed: catalog + blueprints → 8 Turso tables.
//!
//! Load via `JsonStore` (fail-closed validation = R4 write gate), create the
//! pinned DDL, seed from the same JSON files. PK tables upsert by key;
//! keyless tables (`exam_requirements`, `blueprints`) rebuild by
//! DELETE+INSERT (slow-moving, single writer — documented, draft).
//! Parity: COUNT per table. Idempotent. Files stay source.
//!
//! Run: `set -a; source .env; set +a; cargo run --example seed_catalog`

use turso_serverless::Value;
use utmelab_api::{JsonStore, db::Db};

// Phase 4 draft: catalog tables rebuild wholesale (single writer, no
// readers yet — no read path exists and files stay source). This also heals
// the stale pre-pinned `subjects` table found 2026-10-14 (empty, carried
// `full_exam_questions` instead of `objective_paper_questions`).
const DDL: &str = "DROP TABLE IF EXISTS subjects;
DROP TABLE IF EXISTS exams;
DROP TABLE IF EXISTS topics;
DROP TABLE IF EXISTS subtopics;
DROP TABLE IF EXISTS countries;
DROP TABLE IF EXISTS topic_countries;
DROP TABLE IF EXISTS exam_requirements;
DROP TABLE IF EXISTS blueprints;
CREATE TABLE subjects(
  slug TEXT NOT NULL, exam TEXT NOT NULL, name TEXT NOT NULL,
  is_compulsory INTEGER NOT NULL, objective_paper_questions INTEGER,
  PRIMARY KEY (slug, exam)
);
CREATE TABLE IF NOT EXISTS exams(
  code TEXT PRIMARY KEY, name TEXT NOT NULL,
  countries TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL,
  has_full_paper INTEGER, subjects_required INTEGER,
  duration_minutes INTEGER, rules TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS topics(
  slug TEXT PRIMARY KEY, subject TEXT NOT NULL, exam TEXT NOT NULL,
  name TEXT NOT NULL, \"order\" INTEGER NOT NULL,
  weight INTEGER NOT NULL DEFAULT 0,
  objectives TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS subtopics(
  slug TEXT PRIMARY KEY, topic TEXT NOT NULL, name TEXT NOT NULL,
  \"order\" INTEGER NOT NULL, objectives TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS blueprints(
  exam TEXT NOT NULL, subject TEXT NOT NULL, level TEXT NOT NULL,
  topic TEXT, section TEXT, members TEXT NOT NULL DEFAULT '[]',
  paper_size INTEGER NOT NULL,
  pct REAL, pct_low REAL, pct_high REAL,
  expected REAL, expected_low REAL, expected_high REAL,
  source TEXT, sample TEXT, method TEXT NOT NULL, confidence TEXT,
  status TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS countries(
  code TEXT PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topic_countries(
  topic TEXT NOT NULL, country TEXT NOT NULL,
  PRIMARY KEY (topic, country)
);
CREATE TABLE IF NOT EXISTS exam_requirements(
  exam TEXT NOT NULL, country TEXT NOT NULL, \"group\" TEXT NOT NULL,
  min_select INTEGER NOT NULL, subjects TEXT NOT NULL DEFAULT '[]'
);";

fn fail(ctx: &str, e: impl std::fmt::Display) -> ! {
    eprintln!("seed {ctx}: {e}");
    std::process::exit(1);
}

/// Retry a fallible async op with backoff (upserts idempotent, always safe).
macro_rules! retry {
    ($label:expr, $tries:expr, $op:expr) => {{
        let mut attempt = 0u32;
        loop {
            attempt += 1;
            match $op.await {
                Ok(v) => break v,
                Err(e) => {
                    if attempt >= $tries {
                        fail($label, e.to_string());
                    }
                    eprintln!(
                        "seed {}: attempt {attempt} failed, retrying: {}",
                        $label,
                        e.to_string()
                    );
                    std::thread::sleep(std::time::Duration::from_secs(1 << attempt.min(4)));
                }
            }
        }
    }};
}

fn read(file: &str) -> Vec<serde_json::Value> {
    let raw =
        std::fs::read_to_string(format!("data/{file}.json")).unwrap_or_else(|e| fail("read", e));
    serde_json::from_str(&raw).unwrap_or_else(|e| fail("parse", e))
}

fn b(v: &serde_json::Value) -> i64 {
    if v.as_bool().unwrap_or(false) { 1 } else { 0 }
}

fn t(s: &str) -> Value {
    Value::Text(s.to_string())
}

fn ot(v: &serde_json::Value) -> Value {
    match v.as_str() {
        Some(s) => Value::Text(s.to_string()),
        None => Value::Null,
    }
}

fn of(v: &serde_json::Value) -> Value {
    match v.as_f64() {
        Some(f) => Value::Real(f),
        None => Value::Null,
    }
}

fn js(v: &serde_json::Value) -> String {
    serde_json::to_string(v).unwrap_or_else(|_| "[]".to_string())
}

async fn table_count(db: &Db, table: &str) -> i64 {
    let sql = format!("SELECT COUNT(*) FROM {table}");
    let mut q = retry!("count", 6, db.conn().query(&sql, ()));
    q.next()
        .await
        .unwrap_or_else(|e| fail("count-row", e))
        .unwrap_or_else(|| fail("count-empty", "no row"))
        .get(0)
        .unwrap_or_else(|e| fail("count-get", e))
}

#[tokio::main]
async fn main() {
    let url = std::env::var("TURSO_DB_URL").unwrap_or_else(|e| fail("env", e));
    let token = std::env::var("TURSO_DB_TOKEN").unwrap_or_else(|e| fail("env", e));

    // R4 gate: the same loader validates the whole catalog.
    JsonStore::load("data").unwrap_or_else(|e| fail("validate", format!("{e:?}")));

    let subjects = read("subjects");
    let exams = read("exams");
    let topics = read("topics");
    let subtopics = read("subtopics");
    let countries = read("countries");
    let scopes = read("topic_countries");
    let reqs = read("exam_requirements");
    let blueprints = read("blueprints");
    println!(
        "files: subjects={} exams={} topics={} subtopics={} countries={} scopes={} reqs={} blueprints={}",
        subjects.len(),
        exams.len(),
        topics.len(),
        subtopics.len(),
        countries.len(),
        scopes.len(),
        reqs.len(),
        blueprints.len()
    );

    let db = Db::connect(&url, &token)
        .await
        .unwrap_or_else(|e| fail("connect", e));
    retry!("ddl", 6, db.conn().execute_batch(DDL));

    for s in &subjects {
        retry!(
            "upsert",
            6,
            db.conn().execute(
                "INSERT INTO subjects(slug,exam,name,is_compulsory,objective_paper_questions) VALUES(?1,?2,?3,?4,?5) ON CONFLICT(slug,exam) DO UPDATE SET name=excluded.name,is_compulsory=excluded.is_compulsory,objective_paper_questions=excluded.objective_paper_questions",
                (
                    s["slug"].as_str().unwrap_or(""),
                    s["exam"].as_str().unwrap_or(""),
                    s["name"].as_str().unwrap_or(""),
                    b(&s["is_compulsory"]),
                    s["objective_paper_questions"].as_i64(),
                ),
            )
        );
    }
    for e in &exams {
        retry!(
            "upsert",
            6,
            db.conn().execute(
                "INSERT INTO exams(code,name,countries,status,has_full_paper,subjects_required,duration_minutes,rules) VALUES(?1,?2,?3,?4,?5,?6,?7,?8) ON CONFLICT(code) DO UPDATE SET name=excluded.name,countries=excluded.countries,status=excluded.status,has_full_paper=excluded.has_full_paper,subjects_required=excluded.subjects_required,duration_minutes=excluded.duration_minutes,rules=excluded.rules",
                (
                    e["code"].as_str().unwrap_or(""),
                    e["name"].as_str().unwrap_or(""),
                    js(&e["countries"]).as_str(),
                    e["status"].as_str().unwrap_or(""),
                    e["has_full_paper"].as_i64(),
                    e["subjects_required"].as_i64(),
                    e["duration_minutes"].as_i64(),
                    js(&e["rules"]).as_str(),
                ),
            )
        );
    }
    for (i, t) in topics.iter().enumerate() {
        retry!(
            "upsert",
            6,
            db.conn().execute(
                "INSERT INTO topics(slug,subject,exam,name,\"order\",weight,objectives) VALUES(?1,?2,?3,?4,?5,?6,?7) ON CONFLICT(slug) DO UPDATE SET subject=excluded.subject,exam=excluded.exam,name=excluded.name,\"order\"=excluded.\"order\",weight=excluded.weight,objectives=excluded.objectives",
                (
                    t["slug"].as_str().unwrap_or(""),
                    t["subject"].as_str().unwrap_or(""),
                    t["exam"].as_str().unwrap_or(""),
                    t["name"].as_str().unwrap_or(""),
                    t["order"].as_i64().unwrap_or(0),
                    t["weight"].as_i64().unwrap_or(0),
                    js(&t["objectives"]).as_str(),
                ),
            )
        );
        if (i + 1) % 250 == 0 {
            println!("upserted {}/{} topics", i + 1, topics.len());
        }
    }
    for (i, s) in subtopics.iter().enumerate() {
        retry!(
            "upsert",
            6,
            db.conn().execute(
                "INSERT INTO subtopics(slug,topic,name,\"order\",objectives) VALUES(?1,?2,?3,?4,?5) ON CONFLICT(slug) DO UPDATE SET topic=excluded.topic,name=excluded.name,\"order\"=excluded.\"order\",objectives=excluded.objectives",
                (
                    s["slug"].as_str().unwrap_or(""),
                    s["topic"].as_str().unwrap_or(""),
                    s["name"].as_str().unwrap_or(""),
                    s["order"].as_i64().unwrap_or(0),
                    js(&s["objectives"]).as_str(),
                ),
            )
        );
        if (i + 1) % 500 == 0 {
            println!("upserted {}/{} subtopics", i + 1, subtopics.len());
        }
    }
    for c in &countries {
        retry!(
            "upsert",
            6,
            db.conn().execute(
                "INSERT INTO countries(code,name) VALUES(?1,?2) ON CONFLICT(code) DO UPDATE SET name=excluded.name",
                (c["code"].as_str().unwrap_or(""), c["name"].as_str().unwrap_or(""),),
            )
        );
    }
    // topic_countries.json rows are {topic, countries:[...]} — one pair per
    // member country. Empty file today, but the mapping must be right for
    // the day rows exist.
    for r in &scopes {
        let topic = r["topic"].as_str().unwrap_or("");
        let members: Vec<String> =
            serde_json::from_value(r["countries"].clone()).unwrap_or_default();
        for country in &members {
            retry!(
                "upsert",
                6,
                db.conn().execute(
                    "INSERT INTO topic_countries(topic,country) VALUES(?1,?2) ON CONFLICT(topic,country) DO NOTHING",
                    (topic, country.as_str(),),
                )
            );
        }
    }
    // Keyless tables rebuild wholesale (draft: slow-moving, single writer).
    retry!(
        "clear-reqs",
        6,
        db.conn().execute("DELETE FROM exam_requirements", ())
    );
    for r in &reqs {
        retry!(
            "upsert",
            6,
            db.conn().execute(
                "INSERT INTO exam_requirements(exam,country,\"group\",min_select,subjects) VALUES(?1,?2,?3,?4,?5)",
                (
                    r["exam"].as_str().unwrap_or(""),
                    r["country"].as_str().unwrap_or(""),
                    r["group"].as_str().unwrap_or(""),
                    r["min_select"].as_i64().unwrap_or(0),
                    js(&r["subjects"]).as_str(),
                ),
            )
        );
    }
    retry!(
        "clear-blueprints",
        6,
        db.conn().execute("DELETE FROM blueprints", ())
    );
    for bp in &blueprints {
        let params = [
            t(bp["exam"].as_str().unwrap_or("")),
            t(bp["subject"].as_str().unwrap_or("")),
            t(bp["level"].as_str().unwrap_or("")),
            ot(&bp["topic"]),
            ot(&bp["section"]),
            t(js(&bp["members"]).as_str()),
            Value::Integer(bp["paper_size"].as_i64().unwrap_or(0)),
            of(&bp["pct"]),
            of(&bp["pct_low"]),
            of(&bp["pct_high"]),
            of(&bp["expected"]),
            of(&bp["expected_low"]),
            of(&bp["expected_high"]),
            ot(&bp["source"]),
            ot(&bp["sample"]),
            t(bp["method"].as_str().unwrap_or("")),
            ot(&bp["confidence"]),
            t(bp["status"].as_str().unwrap_or("")),
            t(bp["note"].as_str().unwrap_or("")),
        ];
        retry!(
            "upsert",
            6,
            db.conn().execute(
                "INSERT INTO blueprints(exam,subject,level,topic,section,members,paper_size,pct,pct_low,pct_high,expected,expected_low,expected_high,source,sample,method,confidence,status,note) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19)",
                &params,
            )
        );
    }
    println!("upserted all tables");

    // Parity: COUNT per table.
    let expect = [
        ("subjects", subjects.len() as i64),
        ("exams", exams.len() as i64),
        ("topics", topics.len() as i64),
        ("subtopics", subtopics.len() as i64),
        ("countries", countries.len() as i64),
        ("topic_countries", scopes.len() as i64),
        ("exam_requirements", reqs.len() as i64),
        ("blueprints", blueprints.len() as i64),
    ];
    for (table, want) in expect {
        let got = table_count(&db, table).await;
        println!("table {table}: {got} (want {want})");
        if got != want {
            fail("count-parity", format!("{table}: {got} != {want}"));
        }
    }
    println!("PARITY OK: all 8 catalog tables count-equal");
}
