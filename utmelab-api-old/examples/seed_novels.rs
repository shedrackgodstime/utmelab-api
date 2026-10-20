//! Phase 3b seed: validated novel docs → 9 Turso tables.
//!
//! Load via `JsonStore` first (fail-closed validation covers all 6 docs =
//! R4 write gate), then read the docs from disk for seeding — `load()`
//! retains only ≥50q novels for serving, but stubs migrate as ordinary rows
//! and the ≥50 rule moves to the read path. Upsert by id/natural key, then
//! parity: COUNT per table + per-row `content_hash` recompute for
//! `novel_questions`. Idempotent. Files stay source; tables warm standby.
//!
//! Run: `set -a; source .env; set +a; cargo run --example seed_novels`

use utmelab_api::{JsonStore, NovelDoc, db::Db};

const DDL: &str = "CREATE TABLE IF NOT EXISTS novels(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL,
  year_published INTEGER, exam TEXT NOT NULL,
  year_prescribed TEXT NOT NULL DEFAULT '[]',
  category TEXT NOT NULL DEFAULT 'english', featured INTEGER NOT NULL DEFAULT 0,
  synopsis TEXT NOT NULL, setting_place TEXT NOT NULL,
  setting_period TEXT NOT NULL, cover_image TEXT
);
CREATE TABLE IF NOT EXISTS novel_chapters(
  novel_id TEXT NOT NULL, number INTEGER NOT NULL, title TEXT NOT NULL,
  summary TEXT, key_events TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (novel_id, number)
);
CREATE TABLE IF NOT EXISTS novel_characters(
  novel_id TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
  character_type TEXT NOT NULL, description TEXT NOT NULL,
  PRIMARY KEY (novel_id, name)
);
CREATE TABLE IF NOT EXISTS novel_themes(
  novel_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL,
  evidence TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (novel_id, name)
);
CREATE TABLE IF NOT EXISTS novel_questions(
  id TEXT PRIMARY KEY, novel_id TEXT NOT NULL, chapter_number INTEGER,
  text TEXT NOT NULL, inline TEXT NOT NULL DEFAULT '[]',
  options TEXT NOT NULL, answer TEXT NOT NULL, explanation TEXT,
  content_hash TEXT NOT NULL
);";

const DOCS: &[&str] = &[
    "lekki-headmaster",
    "life-changer",
    "second-class-citizen",
    "sweet-sixteen",
    "unexpected-joy-at-dawn",
    "wuthering-heights",
];

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

    // R4 gate: the same loader validates all 6 docs (stubs included).
    JsonStore::load("data").unwrap_or_else(|e| fail("validate", format!("{e:?}")));
    let mut docs: Vec<NovelDoc> = Vec::new();
    for name in DOCS {
        let raw = std::fs::read_to_string(format!("data/novels/{name}.json"))
            .unwrap_or_else(|e| fail("read", e));
        docs.push(serde_json::from_str(&raw).unwrap_or_else(|e| fail("parse", e)));
    }
    let nq: usize = docs.iter().map(|d| d.questions.len()).sum();
    println!("validated docs: {} (questions: {})", docs.len(), nq);

    let db = Db::connect(&url, &token)
        .await
        .unwrap_or_else(|e| fail("connect", e));
    retry!("ddl", 6, db.conn().execute_batch(DDL));

    for d in &docs {
        let n = &d.novel;
        let yp = serde_json::to_string(&n.year_prescribed).unwrap();
        retry!(
            "upsert-novel",
            6,
            db.conn().execute(
                "INSERT INTO novels(id,title,author,year_published,exam,year_prescribed,category,featured,synopsis,setting_place,setting_period,cover_image) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12) ON CONFLICT(id) DO UPDATE SET title=excluded.title,author=excluded.author,year_published=excluded.year_published,exam=excluded.exam,year_prescribed=excluded.year_prescribed,category=excluded.category,featured=excluded.featured,synopsis=excluded.synopsis,setting_place=excluded.setting_place,setting_period=excluded.setting_period,cover_image=excluded.cover_image",
                (
                    n.id.as_str(),
                    n.title.as_str(),
                    n.author.as_str(),
                    n.year_published.map(|y| y as i64),
                    n.exam.as_str(),
                    yp.as_str(),
                    n.category.as_str(),
                    if n.featured { 1i64 } else { 0i64 },
                    n.synopsis.as_str(),
                    n.setting_place.as_str(),
                    n.setting_period.as_str(),
                    n.cover_image.as_deref(),
                ),
            )
        );
        for c in &d.chapters {
            let ke = serde_json::to_string(&c.key_events).unwrap();
            retry!(
                "upsert-chapter",
                6,
                db.conn().execute(
                    "INSERT INTO novel_chapters(novel_id,number,title,summary,key_events) VALUES(?1,?2,?3,?4,?5) ON CONFLICT(novel_id,number) DO UPDATE SET title=excluded.title,summary=excluded.summary,key_events=excluded.key_events",
                    (
                        n.id.as_str(),
                        c.number as i64,
                        c.title.as_str(),
                        c.summary.as_deref(),
                        ke.as_str(),
                    ),
                )
            );
        }
        for c in &d.characters {
            retry!(
                "upsert-character",
                6,
                db.conn().execute(
                    "INSERT INTO novel_characters(novel_id,name,role,character_type,description) VALUES(?1,?2,?3,?4,?5) ON CONFLICT(novel_id,name) DO UPDATE SET role=excluded.role,character_type=excluded.character_type,description=excluded.description",
                    (
                        n.id.as_str(),
                        c.name.as_str(),
                        c.role.as_str(),
                        c.character_type.as_str(),
                        c.description.as_str(),
                    ),
                )
            );
        }
        for t in &d.themes {
            let ev = serde_json::to_string(&t.evidence).unwrap();
            retry!(
                "upsert-theme",
                6,
                db.conn().execute(
                    "INSERT INTO novel_themes(novel_id,name,description,evidence) VALUES(?1,?2,?3,?4) ON CONFLICT(novel_id,name) DO UPDATE SET description=excluded.description,evidence=excluded.evidence",
                    (
                        n.id.as_str(),
                        t.name.as_str(),
                        t.description.as_str(),
                        ev.as_str(),
                    ),
                )
            );
        }
        for (i, q) in d.questions.iter().enumerate() {
            let inline = serde_json::to_string(&q.text.inline).unwrap();
            let options = serde_json::to_string(&q.options).unwrap();
            let explanation = q
                .explanation
                .as_ref()
                .map(|e| serde_json::to_string(e).unwrap());
            let hash = q.content_fingerprint();
            retry!(
                "upsert-nq",
                6,
                db.conn().execute(
                    "INSERT INTO novel_questions(id,novel_id,chapter_number,text,inline,options,answer,explanation,content_hash) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9) ON CONFLICT(id) DO UPDATE SET novel_id=excluded.novel_id,chapter_number=excluded.chapter_number,text=excluded.text,inline=excluded.inline,options=excluded.options,answer=excluded.answer,explanation=excluded.explanation,content_hash=excluded.content_hash",
                    (
                        q.id.as_str(),
                        n.id.as_str(),
                        q.chapter_number.map(|c| c as i64),
                        q.text.text.as_str(),
                        inline.as_str(),
                        options.as_str(),
                        q.answer.as_str(),
                        explanation.as_deref(),
                        hash.as_str(),
                    ),
                )
            );
            if (i + 1) % 100 == 0 {
                println!("upserted {}/{} novel questions", i + 1, nq);
            }
        }
    }
    println!("upserted docs: {}", docs.len());

    // Parity: counts per table + hash recompute for novel_questions.
    let expect = [
        ("novels", docs.len() as i64),
        (
            "novel_chapters",
            docs.iter().map(|d| d.chapters.len()).sum::<usize>() as i64,
        ),
        (
            "novel_characters",
            docs.iter().map(|d| d.characters.len()).sum::<usize>() as i64,
        ),
        (
            "novel_themes",
            docs.iter().map(|d| d.themes.len()).sum::<usize>() as i64,
        ),
        ("novel_questions", nq as i64),
    ];
    for (table, want) in expect {
        let got = table_count(&db, table).await;
        println!("table {table}: {got} (want {want})");
        if got != want {
            fail("count-parity", format!("{table}: {got} != {want}"));
        }
    }

    let mut mismatch = 0usize;
    for d in &docs {
        for q in &d.questions {
            let mut r = retry!(
                "parity-read",
                6,
                db.conn().query(
                    "SELECT content_hash FROM novel_questions WHERE id = ?1",
                    (q.id.as_str(),),
                )
            );
            let got: Option<String> = match r.next().await {
                Ok(Some(row)) => row.get(0).ok(),
                _ => None,
            };
            if got.as_deref() != Some(q.content_fingerprint().as_str()) {
                mismatch += 1;
                if mismatch <= 5 {
                    eprintln!("hash mismatch: {}", q.id);
                }
            }
        }
    }
    println!("hash mismatches: {mismatch}");
    if mismatch != 0 {
        fail("hash-parity", format!("{mismatch} rows differ"));
    }
    println!("PARITY OK: {nq}/{nq} novel questions, counts equal all tables");
}
