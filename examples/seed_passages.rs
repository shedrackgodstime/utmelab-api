//! Phase 3a seed: validated passages → Turso `passages` table.
//!
//! Load via `JsonStore` (fail-closed validation = R4 write gate), upsert by
//! id, then parity: COUNT + full field compare per row. Idempotent.
//! File stays source; table warm standby.
//!
//! Run: `set -a; source .env; set +a; cargo run --example seed_passages`

use utmelab_api::{JsonStore, db::Db};

const DDL: &str = "CREATE TABLE IF NOT EXISTS passages(
  id TEXT PRIMARY KEY,
  exam TEXT NOT NULL, subject TEXT NOT NULL, year INTEGER NOT NULL,
  kind TEXT NOT NULL, title TEXT, author TEXT,
  text TEXT NOT NULL, inline TEXT NOT NULL DEFAULT '[]'
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

#[tokio::main]
async fn main() {
    let url = std::env::var("TURSO_DB_URL").unwrap_or_else(|e| fail("env", e));
    let token = std::env::var("TURSO_DB_TOKEN").unwrap_or_else(|e| fail("env", e));
    let store = JsonStore::load("data").unwrap_or_else(|e| fail("validate", format!("{e:?}")));
    let passages = store.passages();
    println!("validated passages: {}", passages.len());

    let db = Db::connect(&url, &token)
        .await
        .unwrap_or_else(|e| fail("connect", e));
    retry!("ddl", 6, db.conn().execute_batch(DDL));

    for p in passages {
        let inline = serde_json::to_string(&p.text.inline).unwrap();
        retry!(
            "upsert",
            6,
            db.conn().execute(
                "INSERT INTO passages(id,exam,subject,year,kind,title,author,text,inline) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9) ON CONFLICT(id) DO UPDATE SET exam=excluded.exam,subject=excluded.subject,year=excluded.year,kind=excluded.kind,title=excluded.title,author=excluded.author,text=excluded.text,inline=excluded.inline",
                (
                    p.id.as_str(),
                    p.exam.as_str(),
                    p.subject.as_str(),
                    p.year as i64,
                    p.kind.as_str(),
                    p.title.as_deref(),
                    p.author.as_deref(),
                    p.text.text.as_str(),
                    inline.as_str(),
                ),
            )
        );
    }
    println!("upserted: {}", passages.len());

    let mut qc = retry!(
        "count",
        6,
        db.conn().query("SELECT COUNT(*) FROM passages", ())
    );
    let n: i64 = qc
        .next()
        .await
        .unwrap_or_else(|e| fail("count-row", e))
        .unwrap_or_else(|| fail("count-empty", "no row"))
        .get(0)
        .unwrap_or_else(|e| fail("count-get", e));
    println!("table rows: {n}");
    if n as usize != passages.len() {
        fail(
            "count-parity",
            format!("table {n} != file {}", passages.len()),
        );
    }

    let mut mismatch = 0usize;
    for p in passages {
        let mut r = retry!(
            "parity-read",
            6,
            db.conn().query(
                "SELECT exam,subject,year,kind,title,author,text,inline FROM passages WHERE id = ?1",
                (p.id.as_str(),),
            )
        );
        let row = r
            .next()
            .await
            .unwrap_or_else(|e| fail(&format!("parity {}", p.id), e))
            .unwrap_or_else(|| fail(&format!("parity {}", p.id), "missing row"));
        let same = row.get::<String>(0).map(|s| s == p.exam).unwrap_or(false)
            && row
                .get::<String>(1)
                .map(|s| s == p.subject)
                .unwrap_or(false)
            && row
                .get::<i64>(2)
                .map(|y| y as u16 == p.year)
                .unwrap_or(false)
            && row.get::<String>(3).map(|s| s == p.kind).unwrap_or(false)
            && row
                .get::<Option<String>>(4)
                .map(|t| t == p.title)
                .unwrap_or(false)
            && row
                .get::<Option<String>>(5)
                .map(|a| a == p.author)
                .unwrap_or(false)
            && row
                .get::<String>(6)
                .map(|s| s == p.text.text)
                .unwrap_or(false)
            && row
                .get::<String>(7)
                .map(|s| serde_json::to_string(&p.text.inline).unwrap() == s)
                .unwrap_or(false);
        if !same {
            mismatch += 1;
            eprintln!("field mismatch: {}", p.id);
        }
    }
    println!("field mismatches: {mismatch}");
    if mismatch != 0 {
        fail("parity", format!("{mismatch} rows differ"));
    }
    println!(
        "PARITY OK: {n}/{n} rows, all fields equal",
        n = passages.len()
    );
}
