//! Prune `questions` rows the bank no longer holds (D72).
//!
//! `seed_questions` upserts by id, which is right for edits and silently
//! wrong for removals: a row dropped from `data/questions.json` would live on
//! in Turso forever, still served, still counted. Dropping a duplicate is
//! exactly that case, so the mirror needs its other half.
//!
//! Deliberately narrow: it deletes only ids that are **absent from the file**,
//! prints every one of them, and asserts the table count afterwards. No
//! blanket `DELETE`, no table rewrite — the failure mode of a bulk wipe is an
//! empty bank, and the failure mode here is a printed list.
//!
//! Run: `set -a; source .env; set +a; cargo run --example prune_questions`

use std::collections::HashSet;

use turso_serverless::Value;
use utmelab_api::{JsonStore, db::Db};

fn fail(ctx: &str, e: impl std::fmt::Display) -> ! {
    eprintln!("prune {ctx}: {e}");
    std::process::exit(1);
}

/// Turso drops the wire; retries are safe because each delete is idempotent.
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
                    eprintln!("prune {}: attempt {attempt} failed, retrying: {e}", $label);
                    std::thread::sleep(std::time::Duration::from_secs(1 << attempt.min(4)));
                }
            }
        }
    }};
}

async fn column(db: &Db, sql: &str) -> Vec<String> {
    let mut rows = retry!("select", 6, db.conn().query(sql, ()));
    let mut out = Vec::new();
    while let Some(row) = rows.next().await.unwrap_or_else(|e| fail("select-row", e)) {
        out.push(row.get(0).unwrap_or_else(|e| fail("select-get", e)));
    }
    out
}

#[tokio::main]
async fn main() {
    let url = std::env::var("TURSO_DB_URL").unwrap_or_else(|e| fail("env", e));
    let token = std::env::var("TURSO_DB_TOKEN").unwrap_or_else(|e| fail("env", e));

    // The file is the record of what exists (D72: file first, Turso second).
    let store = JsonStore::load("data").unwrap_or_else(|e| fail("validate", format!("{e:?}")));
    let wanted: HashSet<String> = store
        .questions()
        .iter()
        .chain(store.withheld_questions().iter())
        .map(|q| q.id.clone())
        .collect();

    let db = Db::connect(&url, &token)
        .await
        .unwrap_or_else(|e| fail("connect", e));
    let orphans: Vec<String> = column(&db, "SELECT id FROM questions")
        .await
        .into_iter()
        .filter(|id| !wanted.contains(id))
        .collect();

    for id in &orphans {
        let params = [Value::Text(id.clone())];
        retry!(
            "delete",
            6,
            db.conn()
                .execute("DELETE FROM questions WHERE id = ?1", &params)
        );
        println!("pruned {id}");
    }

    let counts = column(&db, "SELECT CAST(COUNT(*) AS TEXT) FROM questions").await;
    let held: usize = counts.first().and_then(|c| c.parse().ok()).unwrap_or(0);
    println!(
        "file holds {}, table holds {}, pruned {}",
        wanted.len(),
        held,
        orphans.len()
    );
    if held != wanted.len() {
        fail(
            "count",
            format!(
                "table holds {held} rows, the file holds {} — re-run seed_questions",
                wanted.len()
            ),
        );
    }
}
