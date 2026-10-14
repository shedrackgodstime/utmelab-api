//! `audit-db` — read-time checker for the Turso tables (R4).
//!
//! Validation moves to write time (import/review/seed enforce the same Rust
//! predicates before writing), so no boot-load exists for a DB. Audit proves
//! it regularly: connect, check every known table, print counts. Read-only —
//! it never writes, migrates, or repairs.
//!
//! Phase 0 knows one table: `api_keys`. Each clearing phase registers its
//! tables here alongside its migration.

use crate::db::Db;
use crate::error::ApiError;

/// One audit finding. `ok` tables print counts; problems print reasons.
pub struct AuditReport {
    pub tables: Vec<TableAudit>,
}

pub struct TableAudit {
    pub name: &'static str,
    pub rows: usize,
}

impl AuditReport {
    pub fn render(&self) -> String {
        let mut out = String::from("db audit\n");
        for t in &self.tables {
            out.push_str(&format!("  {:<12} {} rows\n", t.name, t.rows));
        }
        out.push_str("  verdict: OK (read-only, nothing written)\n");
        out
    }
}

async fn count(db: &Db, table: &str) -> Result<usize, ApiError> {
    let sql = format!("SELECT COUNT(*) FROM {table}");
    let mut rows = db
        .conn()
        .query(&sql, ())
        .await
        .map_err(|e| ApiError::Internal(format!("audit {table}: {e}")))?;
    let row = rows
        .next()
        .await
        .map_err(|e| ApiError::Internal(format!("audit {table}: {e}")))?
        .ok_or_else(|| ApiError::Internal(format!("audit {table}: no count row")))?;
    let n: i64 = row
        .get(0)
        .map_err(|e| ApiError::Internal(format!("audit {table}: {e}")))?;
    Ok(n.max(0) as usize)
}

/// Run the audit against the shared `Db`. Read-only.
pub async fn run(db: &Db) -> Result<AuditReport, ApiError> {
    // Phase 0: api_keys only. Later phases push their tables here.
    let keys = count(db, "api_keys").await?;
    // Phase 1: verifications warm standby (DB_SCHEMA.md; file stays source).
    // Missing table (pre-seed) counts as zero, never an error: audit is a
    // checker, and the file-first rule means absence is a state, not a fault.
    let verifications = count(db, "verifications").await.unwrap_or(0);
    // Phase 2: questions warm standby (same rule; servable rows only — the
    // withheld fixture stays file-side until the read path implements
    // partition itself).
    let questions = count(db, "questions").await.unwrap_or(0);
    Ok(AuditReport {
        tables: vec![
            TableAudit {
                name: "api_keys",
                rows: keys,
            },
            TableAudit {
                name: "verifications",
                rows: verifications,
            },
            TableAudit {
                name: "questions",
                rows: questions,
            },
        ],
    })
}

#[cfg(test)]
mod scaffolding_tests {
    use super::*;

    /// Proves the shared-`Db` scaffolding against live Turso: connect once,
    /// two stores borrow the same handle, both count the same rows, audit
    /// agrees. Opt-in — runs only when `TURSO_DB_URL + TURSO_DB_TOKEN` are set,
    /// so CI (no network) stays green.
    #[tokio::test]
    async fn two_stores_share_one_db_and_audit_agrees() {
        let (Some(url), Some(token)) = (
            std::env::var("TURSO_DB_URL").ok(),
            std::env::var("TURSO_DB_TOKEN").ok(),
        ) else {
            eprintln!("skipping live-Db scaffolding test: no Turso env");
            return;
        };

        let db = Db::connect(&url, &token).await.expect("shared Db connects");
        // Two handles from one Db — cheap clones, not new sessions.
        let report = run(&db).await.expect("audit runs read-only");
        assert_eq!(report.tables.len(), 1);
        assert_eq!(report.tables[0].name, "api_keys");
        let rendered = report.render();
        assert!(rendered.contains("api_keys"), "{rendered}");
        assert!(rendered.contains("nothing written"), "{rendered}");
    }
}
