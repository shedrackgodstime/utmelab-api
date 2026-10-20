//! Phase 2 seed: validated bank → Turso `questions` table.
//!
//! Pinned procedure (docs/DB_SCHEMA.md): load via `JsonStore` (full
//! fail-closed validation = R4 write-time gate), upsert by id with
//! `content_hash` from the shared `content_fingerprint` (R6), then parity:
//! COUNT + per-row hash recomputed from table columns (R1 same structs).
//! Idempotent: re-run whenever the bank moves. File stays source.
//!
//! Run: `set -a; source .env; set +a; cargo run --example seed_questions`

use turso_serverless::{BatchStatement, TransactionBehavior, Value};
use utmelab_api::{Choice, Explanation, JsonStore, Question, RichText, db::Db};

const DDL: &str = "CREATE TABLE IF NOT EXISTS questions(
  id TEXT PRIMARY KEY,
  exam TEXT NOT NULL,
  subject TEXT NOT NULL,
  year INTEGER NOT NULL,
  source TEXT NOT NULL,
  text TEXT NOT NULL,
  inline TEXT NOT NULL DEFAULT '[]',
  options TEXT NOT NULL,
  answer TEXT NOT NULL,
  subtopic_id TEXT,
  section TEXT,
  passage_id TEXT,
  explanation TEXT,
  marks REAL NOT NULL,
  difficulty INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  text_norm TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_q_exam_subject ON questions(exam, subject);
CREATE INDEX IF NOT EXISTS idx_q_subtopic ON questions(subtopic_id);
CREATE INDEX IF NOT EXISTS idx_q_source ON questions(source);
CREATE INDEX IF NOT EXISTS idx_q_year ON questions(year);
CREATE INDEX IF NOT EXISTS idx_q_text_norm ON questions(text_norm);";

// Older tables predate text_norm: add the column when missing. The error
// text is matched, not the code, because turso_serverless surfaces driver
// strings — a duplicate column means another seed already migrated.
const MIGRATE_TEXT_NORM: &str =
    "ALTER TABLE questions ADD COLUMN text_norm TEXT NOT NULL DEFAULT ''";

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

/// One HTTP round trip per CHUNK rows instead of one per row. Each chunk
/// commits all-or-nothing (`transactional_batch`), and upserts are
/// idempotent, so a killed run retries whole chunks on the next pass and
/// can never strand a half-written table.
const CHUNK: usize = 200;

async fn send_chunks(db: &Db, label: &str, stmts: Vec<BatchStatement>, total: usize) {
    let mut done = 0usize;
    for chunk in stmts.chunks(CHUNK) {
        let owned = chunk.to_vec();
        retry!(
            label,
            6,
            db.conn()
                .transactional_batch(owned.clone(), TransactionBehavior::Immediate)
        );
        done += chunk.len();
        println!("{label} {done}/{total}");
    }
}

const QUESTION_UPSERT: &str = "INSERT INTO questions(id,exam,subject,year,source,text,inline,options,answer,subtopic_id,section,passage_id,explanation,marks,difficulty,content_hash,text_norm) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17) ON CONFLICT(id) DO UPDATE SET exam=excluded.exam,subject=excluded.subject,year=excluded.year,source=excluded.source,text=excluded.text,inline=excluded.inline,options=excluded.options,answer=excluded.answer,subtopic_id=excluded.subtopic_id,section=excluded.section,passage_id=excluded.passage_id,explanation=excluded.explanation,marks=excluded.marks,difficulty=excluded.difficulty,content_hash=excluded.content_hash,text_norm=excluded.text_norm";

#[tokio::main]
async fn main() {
    let url = std::env::var("TURSO_DB_URL").unwrap_or_else(|e| fail("env", e));
    let token = std::env::var("TURSO_DB_TOKEN").unwrap_or_else(|e| fail("env", e));

    // R4: the same fail-closed validation boot runs, here as the write gate.
    let store = JsonStore::load("data").unwrap_or_else(|e| fail("validate", format!("{e:?}")));
    // Servable plus withheld (D58): every valid row seeds, so the table
    // holds the whole bank and the read path partitions identically.
    let questions: Vec<_> = store
        .questions()
        .iter()
        .chain(store.withheld_questions().iter())
        .collect();
    println!(
        "validated questions: {} ({} withheld)",
        questions.len(),
        store.withheld_questions().len()
    );

    let db = Db::connect(&url, &token)
        .await
        .unwrap_or_else(|e| fail("connect", e));
    retry!("ddl", 6, db.conn().execute_batch(DDL));
    // Backfill-era tables lack text_norm: add it once, ignore the call when
    // a previous seed already did.
    match db.conn().execute(MIGRATE_TEXT_NORM, ()).await {
        Ok(_) => println!("migrated: text_norm column added"),
        Err(e) if e.to_string().contains("duplicate column") => {}
        Err(e) => fail("migrate-text-norm", e.to_string()),
    }

    let mut stmts = Vec::with_capacity(questions.len());
    for q in questions.iter() {
        let inline = serde_json::to_string(&q.text.inline).unwrap();
        let options = serde_json::to_string(&q.options).unwrap();
        let explanation = q
            .explanation
            .as_ref()
            .map(|e| serde_json::to_string(e).unwrap());
        let hash = q.content_fingerprint();
        // Rust-side lowercase, stored once: Turso LOWER() is ASCII-only, so a
        // SQL-side lowering would silently change ?q= results on diacritics.
        let text_norm = q.text.text.to_lowercase();
        // 17 params exceeds the driver's 16-tuple impl, so a Vec it is.
        let params = vec![
            Value::from(q.id.as_str()),
            Value::from(q.exam.as_str()),
            Value::from(q.subject.as_str()),
            Value::from(q.year as i64),
            Value::from(q.source.as_str()),
            Value::from(q.text.text.as_str()),
            Value::from(inline.as_str()),
            Value::from(options.as_str()),
            Value::from(q.answer.as_str()),
            Value::from(q.subtopic_id.as_deref()),
            Value::from(q.section.as_deref()),
            Value::from(q.passage_id.as_deref()),
            Value::from(explanation.as_deref()),
            Value::from(q.marks as f64),
            Value::from(q.difficulty as i64),
            Value::from(hash.as_str()),
            Value::from(text_norm.as_str()),
        ];
        stmts.push(
            BatchStatement::new(QUESTION_UPSERT, params)
                .unwrap_or_else(|e| fail("params", e.to_string())),
        );
    }
    send_chunks(&db, "questions", stmts, questions.len()).await;
    println!("upserted: {}", questions.len());

    // Parity: COUNT + per-row hash recomputed from table columns (R1/R6).
    let sql = "SELECT COUNT(*) FROM questions";
    let mut qc = retry!("count", 6, db.conn().query(&sql, ()));
    let n: i64 = qc
        .next()
        .await
        .unwrap_or_else(|e| fail("count-row", e))
        .unwrap_or_else(|| fail("count-empty", "no row"))
        .get(0)
        .unwrap_or_else(|e| fail("count-get", e));
    println!("table rows: {n}");
    if n as usize != questions.len() {
        fail(
            "count-parity",
            format!("table {n} != file {}", questions.len()),
        );
    }
    let mut mismatch = 0usize;
    for q in questions.iter() {
        let mut r = retry!(
            "parity-read",
            6,
            db.conn().query(
                "SELECT exam,subject,year,source,text,inline,options,answer,subtopic_id,section,passage_id,explanation,marks,difficulty,content_hash FROM questions WHERE id = ?1",
                (q.id.as_str(),),
            )
        );
        let row = r
            .next()
            .await
            .unwrap_or_else(|e| fail(&format!("parity {}", q.id), e))
            .unwrap_or_else(|| fail(&format!("parity {}", q.id), "missing row"));
        let rebuilt = Question {
            id: q.id.clone(),
            exam: row.get(0).unwrap_or_else(|e| fail("re-exam", e)),
            subject: row.get(1).unwrap_or_else(|e| fail("re-subject", e)),
            year: {
                let y: i64 = row.get(2).unwrap_or_else(|e| fail("re-year", e));
                y as u16
            },
            source: row.get(3).unwrap_or_else(|e| fail("re-source", e)),
            text: RichText {
                text: row.get(4).unwrap_or_else(|e| fail("re-text", e)),
                inline: {
                    let s: String = row.get(5).unwrap_or_else(|e| fail("re-inline", e));
                    serde_json::from_str(&s).unwrap_or_else(|e| fail("re-inline-json", e))
                },
            },
            options: {
                let s: String = row.get(6).unwrap_or_else(|e| fail("re-options", e));
                serde_json::from_str::<Vec<Choice>>(&s)
                    .unwrap_or_else(|e| fail("re-options-json", e))
            },
            answer: row.get(7).unwrap_or_else(|e| fail("re-answer", e)),
            subtopic_id: row.get(8).unwrap_or_else(|e| fail("re-subtopic", e)),
            section: row.get(9).unwrap_or_else(|e| fail("re-section", e)),
            passage_id: row.get(10).unwrap_or_else(|e| fail("re-passage", e)),
            explanation: row
                .get::<Option<String>>(11)
                .unwrap_or_else(|e| fail("re-expl", e))
                .map(|s| {
                    serde_json::from_str::<Explanation>(&s)
                        .unwrap_or_else(|e| fail("re-expl-json", e))
                }),
            marks: {
                let m: f64 = row.get(12).unwrap_or_else(|e| fail("re-marks", e));
                m as f32
            },
            difficulty: {
                let d: i64 = row.get(13).unwrap_or_else(|e| fail("re-diff", e));
                d as u8
            },
            verified: false,
        };
        let table_hash: String = row.get(14).unwrap_or_else(|e| fail("re-hash", e));
        if rebuilt.content_fingerprint() != q.content_fingerprint()
            || table_hash != q.content_fingerprint()
        {
            mismatch += 1;
            if mismatch <= 5 {
                eprintln!("hash mismatch: {}", q.id);
            }
        }
    }
    println!("hash mismatches: {mismatch}");
    if mismatch != 0 {
        fail("hash-parity", format!("{mismatch} rows differ"));
    }
    println!(
        "PARITY OK: {n}/{n} rows, per-row fingerprint equal",
        n = questions.len()
    );
}
