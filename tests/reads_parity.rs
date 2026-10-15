//! Parity: `SqlReads` (per-request SQL) against `JsonStore` (in-RAM scan).
//!
//! Same rows in both: a local libsql file seeded from the loaded bank
//! (questions with live fingerprints, all verifications, full subtopics)
//! versus the file loader itself. Any filter combo must return identical
//! ids in identical order with identical totals and verified flags.
//! Randomized shapes, so a lucky subset cannot hide a semantic gap.

use std::path::PathBuf;

use utmelab_api::{JsonStore, Question, QuestionFilter, SqlReads, Store};

fn repo_data() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data")
}

/// TEXT-or-NULL, exactly like the seeds write it: strings verbatim,
/// missing/null as NULL, structures as compact JSON.
fn txt(json: &serde_json::Value) -> libsql::Value {
    match json {
        serde_json::Value::Null => libsql::Value::Null,
        serde_json::Value::String(s) => libsql::Value::Text(s.clone()),
        other => libsql::Value::Text(other.to_string()),
    }
}

fn int(json: &serde_json::Value) -> libsql::Value {
    json.as_i64()
        .map(libsql::Value::Integer)
        .unwrap_or(libsql::Value::Null)
}

async fn fixture_db(path: &std::path::Path, bank: &JsonStore) {
    let db = libsql::Builder::new_local(path).build().await.unwrap();
    let conn = db.connect().unwrap();
    conn.execute_batch(
        "CREATE TABLE questions(id TEXT PRIMARY KEY,exam TEXT,subject TEXT,year INTEGER,\
         source TEXT,text TEXT,inline TEXT,options TEXT,answer TEXT,subtopic_id TEXT,\
         section TEXT,passage_id TEXT,explanation TEXT,marks REAL,difficulty INTEGER,\
         content_hash TEXT,text_norm TEXT);
         CREATE TABLE verifications(id TEXT PRIMARY KEY,question_id TEXT,kind TEXT,\
         verdict TEXT,scope TEXT,verifier TEXT,detail TEXT,content_hash TEXT,created_at TEXT);
         CREATE TABLE subtopics(slug TEXT PRIMARY KEY,topic TEXT,name TEXT,\
         \"order\" INTEGER,objectives TEXT);
         CREATE TABLE topic_countries(topic TEXT,country TEXT);",
    )
    .await
    .unwrap();

    let raw_questions: Vec<serde_json::Value> =
        serde_json::from_str(&std::fs::read_to_string(repo_data().join("questions.json")).unwrap())
            .unwrap();
    let by_id: std::collections::HashMap<&str, &Question> = bank
        .questions()
        .iter()
        .map(|q| (q.id.as_str(), q))
        .collect();
    for q in &raw_questions {
        let id = q["id"].as_str().unwrap();
        // Only servable rows: withheld rows live beside the bank, never in
        // `questions()`, so parity compares exactly what routes can serve.
        let Some(live) = by_id.get(id) else {
            continue;
        };
        let text = q["text"]["text"].as_str().unwrap_or("");
        conn.execute(
            "INSERT INTO questions VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17)",
            [
                txt(&q["id"]),
                txt(&q["exam"]),
                txt(&q["subject"]),
                int(&q["year"]),
                txt(&q["source"]),
                libsql::Value::Text(text.to_owned()),
                txt(&q["text"]["inline"]),
                txt(&q["options"]),
                txt(&q["answer"]),
                txt(&q["subtopic_id"]),
                txt(&q["section"]),
                txt(&q["passage_id"]),
                txt(&q["explanation"]),
                q["marks"]
                    .as_f64()
                    .map(libsql::Value::Real)
                    .unwrap_or(libsql::Value::Null),
                int(&q["difficulty"]),
                libsql::Value::Text(live.content_fingerprint()),
                libsql::Value::Text(text.to_lowercase()),
            ],
        )
        .await
        .unwrap();
    }

    let verifications: Vec<serde_json::Value> = serde_json::from_str(
        &std::fs::read_to_string(repo_data().join("verifications.json")).unwrap(),
    )
    .unwrap();
    for v in &verifications {
        conn.execute(
            "INSERT INTO verifications VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)",
            [
                txt(&v["id"]),
                txt(&v["question_id"]),
                // Seeds write enums bare (human, pass), not JSON-quoted.
                libsql::Value::Text(v["kind"].as_str().unwrap_or("").to_owned()),
                libsql::Value::Text(v["verdict"].as_str().unwrap_or("").to_owned()),
                txt(&v["scope"]),
                txt(&v["verifier"]),
                txt(&v["detail"]),
                txt(&v["content_hash"]),
                txt(&v["created_at"]),
            ],
        )
        .await
        .unwrap();
    }

    let subtopics: Vec<serde_json::Value> =
        serde_json::from_str(&std::fs::read_to_string(repo_data().join("subtopics.json")).unwrap())
            .unwrap();
    for s in &subtopics {
        conn.execute(
            "INSERT INTO subtopics VALUES(?1,?2,?3,?4,?5)",
            [
                txt(&s["slug"]),
                txt(&s["topic"]),
                txt(&s["name"]),
                s["order"]
                    .as_i64()
                    .map(libsql::Value::Integer)
                    .unwrap_or(libsql::Value::Null),
                txt(&s["objectives"]),
            ],
        )
        .await
        .unwrap();
    }
}

fn filters() -> Vec<QuestionFilter<'static>> {
    let mut out = vec![QuestionFilter::default()];
    let combo: Vec<QuestionFilter<'static>> = vec![
        QuestionFilter {
            exam: Some("JAMB"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            exam: Some("JAMB"),
            subject: Some("mathematics"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            exam: Some("JAMB"),
            subject: Some("use-of-english"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            subtopic: Some("surds"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            subtopic: Some("no-such-subtopic"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            verified: Some(true),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            verified: Some(false),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            exam: Some("JAMB"),
            verified: Some(true),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            source: Some("past_paper"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            year: Some(2025),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            text: Some("passage"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            text: Some("PASSAGE"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            text: Some("100%"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            text: Some("under_score"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            text: Some("ɗan"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            text: Some("É"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            exam: Some("NOPE"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            subject: Some("nope"),
            ..QuestionFilter::default()
        },
        QuestionFilter {
            exam: Some("JAMB"),
            subject: Some("physics"),
            subtopic: Some("thermometric-properties"),
            verified: Some(true),
            source: Some("authored"),
            year: Some(2025),
            text: Some("heat"),
            ..QuestionFilter::default()
        },
    ];
    out.extend(combo);
    // Country variants of a few combos.
    for country in [Some("GH"), Some("NG"), Some("XX")] {
        out.push(QuestionFilter {
            country,
            ..QuestionFilter::default()
        });
        out.push(QuestionFilter {
            exam: Some("WAEC"),
            country,
            ..QuestionFilter::default()
        });
    }
    out
}

#[tokio::test]
async fn sql_reads_match_the_ram_bank_on_every_filter() {
    let path = std::env::temp_dir().join(format!(
        "utmelab-parity-{}-{}.db",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let bank = JsonStore::load(repo_data()).expect("file bank loads");
    fixture_db(&path, &bank).await;
    let reads = SqlReads::new(libsql::Builder::new_local(&path).build().await.unwrap());

    for (n, filter) in filters().iter().enumerate() {
        for (page, per_page) in [
            (1, 50),
            (2, 5),
            (1, 200),
            (7, 3),
            (0, 0),
            (1, 999),
            (99, 50),
        ] {
            let want = bank.questions_page(filter.clone(), page, per_page);
            let got = reads
                .questions_page(filter.clone(), page, per_page)
                .await
                .unwrap_or_else(|e| panic!("filter {n} page {page}/{per_page}: {e}"));
            assert_eq!(got.page, want.page, "page echo {n}");
            assert_eq!(got.per_page, want.per_page, "per_page echo {n}");
            assert_eq!(
                got.total_records, want.total_records,
                "totals differ filter {n} {filter:?}"
            );
            let want_ids: Vec<&str> = want.questions.iter().map(|q| q.id.as_str()).collect();
            let got_ids: Vec<&str> = got.questions.iter().map(|q| q.id.as_str()).collect();
            assert_eq!(got_ids, want_ids, "order/ids differ filter {n} {filter:?}");
            for (a, b) in got.questions.iter().zip(want.questions.iter()) {
                assert_eq!(
                    a.verified, b.verified,
                    "verified differs {} filter {n}",
                    a.id
                );
                assert_eq!(a.answer, b.answer, "answer differs {} filter {n}", a.id);
                assert_eq!(a.text.text, b.text.text, "stem differs {} filter {n}", a.id);
            }
        }
    }

    // By-id: a spread of rows including passage-linked and verified ones.
    let bank_ids: Vec<String> = bank
        .questions_page(QuestionFilter::default(), 1, 200)
        .questions
        .iter()
        .take(200)
        .map(|q| q.id.clone())
        .collect();
    for id in bank_ids.iter().step_by(7) {
        let want = bank.question(id).expect("id exists");
        let got = reads.question_by_id(id).await.unwrap().expect("id exists");
        assert_eq!(got.id, want.id);
        assert_eq!(got.verified, want.verified, "verified differs {id}");
        assert_eq!(got.passage_id, want.passage_id, "passage differs {id}");
    }
    assert!(reads.question_by_id("no-such-id").await.unwrap().is_none());

    let _ = std::fs::remove_file(&path);
}
