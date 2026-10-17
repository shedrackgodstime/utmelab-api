//! Disk-cache path (boot accelerator). Opt-in — needs `TURSO_DB_URL` +
//! `TURSO_DB_TOKEN`, so CI stays green.
//!
//! Miss writes the cache, hit reads it: both boots must serve identical
//! banks. Uses a temp file, never `var/`, so the test cannot pollute prod.

use utmelab_api::{Db, Store, TursoStore};

#[tokio::test]
async fn disk_cache_miss_then_hit_serve_identical_banks() {
    let (Some(url), Some(token)) = (
        std::env::var("TURSO_DB_URL").ok(),
        std::env::var("TURSO_DB_TOKEN").ok(),
    ) else {
        eprintln!("skipping bank cache test: no Turso env");
        return;
    };
    let cache =
        std::env::temp_dir().join(format!("utmelab-cache-test-{}.json", std::process::id()));
    let _ = std::fs::remove_file(&cache);

    let db = Db::connect(&url, &token).await.expect("turso connects");
    // Miss: full fetch, writes cache.
    let miss = TursoStore::open_cached(&db, &cache)
        .await
        .expect("miss boots");
    assert!(cache.is_file(), "miss writes the cache file");
    // Hit: disk load, same content.
    let hit = TursoStore::open_cached(&db, &cache)
        .await
        .expect("hit boots");
    assert_eq!(hit.version(), miss.version(), "same version");
    assert_eq!(
        hit.question_count(),
        miss.question_count(),
        "same questions"
    );
    assert_eq!(hit.subject_count(), miss.subject_count(), "same subjects");
    assert_eq!(
        hit.subtopic_counts(),
        miss.subtopic_counts(),
        "same coverage"
    );
    let _ = std::fs::remove_file(&cache);
}
