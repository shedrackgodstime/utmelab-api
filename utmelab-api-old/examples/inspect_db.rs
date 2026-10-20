//! Throwaway inspector: tables, counts, DDL. Read-only.
use utmelab_api::db::Db;

fn fail(ctx: &str, e: impl std::fmt::Display) -> ! {
    eprintln!("inspect {ctx}: {e}");
    std::process::exit(1);
}

#[tokio::main]
async fn main() {
    let url = std::env::var("TURSO_DB_URL").unwrap_or_else(|e| fail("env", e));
    let token = std::env::var("TURSO_DB_TOKEN").unwrap_or_else(|e| fail("env", e));
    let db = Db::connect(&url, &token)
        .await
        .unwrap_or_else(|e| fail("connect", e));
    let mut q = db
        .conn()
        .query(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
            (),
        )
        .await
        .unwrap_or_else(|e| fail("tables", e));
    println!("TABLES:");
    while let Some(r) = q.next().await.unwrap_or_else(|e| fail("row", e)) {
        let name: String = r.get(0).unwrap_or_else(|e| fail("name", e));
        println!("  {name}");
    }
    for t in [
        "subjects",
        "exams",
        "topics",
        "subtopics",
        "countries",
        "topic_countries",
        "exam_requirements",
        "blueprints",
        "questions",
        "verifications",
        "passages",
        "novels",
        "novel_questions",
        "api_keys",
    ] {
        let sql = format!("SELECT COUNT(*) FROM {t}");
        let mut q = db
            .conn()
            .query(&sql, ())
            .await
            .unwrap_or_else(|e| fail("count", e));
        let n: i64 = q
            .next()
            .await
            .unwrap_or_else(|e| fail("count-row", e))
            .unwrap_or_else(|| fail("count-empty", "no row"))
            .get(0)
            .unwrap_or_else(|e| fail("count-get", e));
        println!("{t}: {n}");
    }
    for t in ["subjects", "exams", "topics", "blueprints"] {
        let sql = format!("SELECT sql FROM sqlite_master WHERE name='{t}'");
        let mut q = db
            .conn()
            .query(&sql, ())
            .await
            .unwrap_or_else(|e| fail("ddl", e));
        if let Some(r) = q.next().await.unwrap_or_else(|e| fail("ddl-row", e)) {
            let s: String = r.get(0).unwrap_or_else(|e| fail("ddl-get", e));
            println!("--- {t} DDL ---\n{s}");
        }
    }
}
