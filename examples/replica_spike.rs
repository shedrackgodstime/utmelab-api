//! Replica spike: is a local synced file faster and smaller than the
//! full-RAM bank? Read-only against production data; writes nothing anywhere.
//!
//! Run: `set -a; source .env; set +a; cargo run --example replica_spike`
//!
//! What it measures, side by side:
//!   A. current path — `TursoStore::open` (full fetch over the wire into RAM)
//!   B. replica path — one `sync()` into a local file, then the same page a
//!      `/questions` handler serves, straight from that file, 200 times.
//!
//! Both paths print wall time and process RSS, so the trade is numbers, not
//! adjectives. The replica file lands in the OS temp dir and is deleted
//! afterwards; the production database is never written to.

use std::time::{Duration, Instant};

use utmelab_api::{Db, Store, TursoStore};

const PAGE_SQL: &str = "SELECT id,exam,subject,year,source,text,inline,options,answer,\
    subtopic_id,section,passage_id,explanation,marks,difficulty \
    FROM questions WHERE exam='JAMB' AND subject='use-of-english' \
    ORDER BY id LIMIT 50";

/// Whole-process resident set, MiB. Reads the kernel, not an allocator.
fn rss_mib() -> f64 {
    let status = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
    for line in status.lines() {
        if let Some(rest) = line.strip_prefix("VmRSS:") {
            let kb: f64 = rest
                .split_whitespace()
                .next()
                .and_then(|n| n.parse().ok())
                .unwrap_or(0.0);
            return kb / 1024.0;
        }
    }
    f64::NAN
}

fn percentile(sorted_ms: &mut [f64], pct: f64) -> f64 {
    if sorted_ms.is_empty() {
        return f64::NAN;
    }
    sorted_ms.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let at = ((pct / 100.0) * (sorted_ms.len() as f64 - 1.0)).round() as usize;
    sorted_ms[at.min(sorted_ms.len() - 1)]
}

fn fail(stage: &str, e: impl std::fmt::Display) -> ! {
    eprintln!("spike failed at {stage}: {e}");
    std::process::exit(1);
}

#[tokio::main]
async fn main() {
    let url = std::env::var("TURSO_DB_URL").unwrap_or_else(|e| fail("env TURSO_DB_URL", e));
    let token = std::env::var("TURSO_DB_TOKEN").unwrap_or_else(|e| fail("env TURSO_DB_TOKEN", e));

    // ── A. current path: full fetch into RAM ──────────────────────────
    let rss_before = rss_mib();
    let t = Instant::now();
    let db = Db::connect(&url, &token)
        .await
        .unwrap_or_else(|e| fail("remote connect", e));
    let store = TursoStore::open(db)
        .await
        .unwrap_or_else(|e| fail("TursoStore::open", e));
    let open_secs = t.elapsed().as_secs_f64();
    let rss_after_open = rss_mib();
    println!(
        "A  full-fetch into RAM : {:>8.2}s  questions={}  RSS {:.1} -> {:.1} MiB",
        open_secs,
        store.question_count(),
        rss_before,
        rss_after_open,
    );

    // ── B. replica path: sync once, then read pages from the file ─────
    let replica_path =
        std::env::temp_dir().join(format!("utmelab-spike-{}.db", std::process::id()));
    let _ = std::fs::remove_file(&replica_path);
    let t = Instant::now();
    let replica = libsql::Builder::new_remote_replica(&replica_path, url.clone(), token.clone())
        .build()
        .await
        .unwrap_or_else(|e| fail("replica build", e));
    let sync_t = Instant::now();
    let frames = replica
        .sync()
        .await
        .unwrap_or_else(|e| fail("replica sync (token needs sync permission)", e));
    let sync_secs = sync_t.elapsed().as_secs_f64();
    let file_bytes = std::fs::metadata(&replica_path)
        .map(|m| m.len())
        .unwrap_or(0);
    println!(
        "B  replica sync        : {:>8.2}s  frames={}  file={:.1} MiB (total {:.2}s with build)",
        sync_secs,
        frames.frames_synced(),
        file_bytes as f64 / 1048576.0,
        t.elapsed().as_secs_f64(),
    );

    let conn = replica
        .connect()
        .unwrap_or_else(|e| fail("replica connect", e));
    // Warm the page cache the way a running server would have it warm.
    for _ in 0..5 {
        let mut rows = conn
            .query(PAGE_SQL, ())
            .await
            .unwrap_or_else(|e| fail("warmup page", e));
        while rows
            .next()
            .await
            .unwrap_or_else(|e| fail("warmup row", e))
            .is_some()
        {}
    }
    let mut samples = Vec::with_capacity(200);
    let mut cells = 0usize;
    for _ in 0..200 {
        let t = Instant::now();
        let mut rows = conn
            .query(PAGE_SQL, ())
            .await
            .unwrap_or_else(|e| fail("page query", e));
        let mut n = 0;
        while let Some(row) = rows.next().await.unwrap_or_else(|e| fail("page row", e)) {
            // Touch every column the handler would serialize, so the read
            // is real work and not a skipped cursor.
            for i in 0..15 {
                if row.get_value(i).is_ok() {
                    cells += 1;
                }
            }
            n += 1;
        }
        assert_eq!(n, 50, "page shape changed under the spike");
        samples.push(t.elapsed().as_secs_f64() * 1000.0);
    }
    let rss_after_pages = rss_mib();
    println!(
        "B  page x200 (50 rows): p50={:>7.2}ms p99={:>7.2}ms  cells={}  RSS {:.1} MiB",
        percentile(&mut samples.clone(), 50.0),
        percentile(&mut samples, 99.0),
        cells,
        rss_after_pages,
    );

    let _ = std::fs::remove_file(&replica_path);
    let _ = Duration::from_secs(0);
    println!("spike done: replica file removed, production untouched");
}
