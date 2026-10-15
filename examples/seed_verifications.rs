//! Phase 1 re-seed: `data/verifications.json` → Turso `verifications` table.
//!
//! Pinned procedure (docs/DB_SCHEMA.md): read file → upsert by id → count +
//! per-row `content_hash` parity. Idempotent: re-run whenever the file moves.
//! The file stays source of truth; the table is a warm standby.
//!
//! Run: `set -a; source .env; set +a; cargo run --example seed_verifications`

use turso_serverless::{BatchStatement, TransactionBehavior};
use utmelab_api::Verification;
use utmelab_api::db::Db;

const DDL: &str = "CREATE TABLE IF NOT EXISTS verifications(
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  verdict TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT '[]',
  verifier TEXT NOT NULL,
  detail TEXT,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ver_q ON verifications(question_id, created_at);";

fn fail(ctx: &str, e: impl std::fmt::Display) -> ! {
    eprintln!("seed {ctx}: {e}");
    std::process::exit(1);
}

/// Retry a fallible async op with backoff. The wire to Turso drops
/// occasionally; upserts are idempotent so retrying is always safe.
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
/// commits all-or-nothing, and every statement here is an idempotent upsert.
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

#[tokio::main]
async fn main() {
    let url = std::env::var("TURSO_DB_URL").unwrap_or_else(|e| fail("env", e));
    let token = std::env::var("TURSO_DB_TOKEN").unwrap_or_else(|e| fail("env", e));
    let raw =
        std::fs::read_to_string("data/verifications.json").unwrap_or_else(|e| fail("read", e));
    let rows: Vec<Verification> = serde_json::from_str(&raw).unwrap_or_else(|e| fail("parse", e));
    println!("file rows: {}", rows.len());

    let db = Db::connect(&url, &token)
        .await
        .unwrap_or_else(|e| fail("connect", e));
    db.conn()
        .execute_batch(DDL)
        .await
        .unwrap_or_else(|e| fail("ddl", e));

    let mut stmts = Vec::with_capacity(rows.len());
    for v in rows.iter() {
        let kind = serde_json::to_value(v.kind).unwrap();
        let verdict = serde_json::to_value(v.verdict).unwrap();
        let scope = serde_json::to_string(&v.scope).unwrap();
        stmts.push(
            BatchStatement::new(
                "INSERT INTO verifications(id,question_id,kind,verdict,scope,verifier,detail,content_hash,created_at) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9) ON CONFLICT(id) DO UPDATE SET question_id=excluded.question_id,kind=excluded.kind,verdict=excluded.verdict,scope=excluded.scope,verifier=excluded.verifier,detail=excluded.detail,content_hash=excluded.content_hash,created_at=excluded.created_at",
                (
                    v.id.as_str(),
                    v.question_id.as_str(),
                    kind.as_str().unwrap_or(""),
                    verdict.as_str().unwrap_or(""),
                    scope.as_str(),
                    v.verifier.as_str(),
                    v.detail.as_deref(),
                    v.content_hash.as_str(),
                    v.created_at.as_str(),
                ),
            )
            .unwrap_or_else(|e| fail("params", e.to_string())),
        );
    }
    send_chunks(&db, "verifications", stmts, rows.len()).await;
    println!("upserted: {}", rows.len());

    // Parity: count + per-row content_hash.
    let mut q = db
        .conn()
        .query("SELECT COUNT(*) FROM verifications", ())
        .await
        .unwrap_or_else(|e| fail("count", e));
    let n: i64 = q
        .next()
        .await
        .unwrap_or_else(|e| fail("count-row", e))
        .unwrap_or_else(|| fail("count-empty", "no row"))
        .get(0)
        .unwrap_or_else(|e| fail("count-get", e));
    println!("table rows: {n}");
    if n as usize != rows.len() {
        fail("count-parity", format!("table {n} != file {}", rows.len()));
    }

    let mut mismatch = 0usize;
    for v in &rows {
        let mut q = db
            .conn()
            .query(
                "SELECT content_hash FROM verifications WHERE id = ?1",
                (v.id.as_str(),),
            )
            .await
            .unwrap_or_else(|e| fail(&format!("parity {}", v.id), e));
        let got: Option<String> = match q.next().await {
            Ok(Some(r)) => r.get(0).ok(),
            _ => None,
        };
        if got.as_deref() != Some(v.content_hash.as_str()) {
            mismatch += 1;
            if mismatch <= 5 {
                eprintln!(
                    "hash mismatch: {} file={} table={:?}",
                    v.id, v.content_hash, got
                );
            }
        }
    }
    println!("hash mismatches: {mismatch}");
    if mismatch != 0 {
        fail("hash-parity", format!("{mismatch} rows differ"));
    }
    println!(
        "PARITY OK: {n}/{n} rows, per-row content_hash equal",
        n = rows.len()
    );
}
