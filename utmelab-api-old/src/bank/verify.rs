//! Review writes a verification row (W1).
//!
//! Production verifications go through here, not through file appends:
//! the same gates `review.py` enforces (flags clear, explanation present),
//! the same row shape, then **file first, Turso second** — the file write
//! lands first so any gap heals on the next idempotent re-seed; the reverse
//! order would leave twins nothing can heal. The disk cache is refreshed
//! implicitly: the next boot sees a new content version and refetches.

use crate::bank::TursoStore;
use crate::bank::store::Store;
use crate::db::Db;
use crate::error::ApiError;
use crate::{Verdict, Verification, VerifyCheck, VerifyKind, quarantine};

fn internal(ctx: &str, e: impl std::fmt::Display) -> ApiError {
    ApiError::Internal(format!("verify {ctx}: {e}"))
}

/// Seconds-precision UTC (`2026-10-14T01:23:45Z`) — the file convention.
/// Lexicographic order must equal chronological order because derivation
/// sorts `(created_at, id)`.
/// Seconds-precision UTC (`2026-10-14T01:23:45Z`) — the file convention.
/// Lexicographic order must equal chronological order because derivation
/// sorts `(created_at, id)`.
pub fn now_iso_utc() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    iso_of(secs)
}

/// Run the review gates and write the row: file first, Turso second.
/// Returns the human line (`verified <id>` / `<id> already verified`).
/// Refusals are errors naming the blocker, same contract as `review.py`.
pub async fn verify_row(
    db: &Db,
    cache_path: &std::path::Path,
    data_dir: &std::path::Path,
    question_id: &str,
    verifier: &str,
) -> Result<String, ApiError> {
    let store = TursoStore::open_cached(db, cache_path).await?;
    let q = store
        .question(question_id)
        .ok_or_else(|| ApiError::not_found("question_not_found", question_id))?
        .clone();
    if q.verified {
        return Ok(format!("{question_id} already verified"));
    }
    let flags: Vec<String> = quarantine::scan(&store)
        .into_iter()
        .filter(|f| f.id == question_id)
        .map(|f| f.kind.to_string())
        .collect();
    if !flags.is_empty() {
        return Err(ApiError::config(format!(
            "Resolve first: {}",
            flags.join(", ")
        )));
    }
    if q.explanation.is_none() {
        return Err(ApiError::config(
            "Verified claims the working was checked — write the explanation first.",
        ));
    }
    let hash = q.content_fingerprint();
    let created_at = now_iso_utc();

    // Collision-free row id: count twins, bump while taken. Two writers can
    // still race, but the id is a primary key — the loser retries, never
    // silently overwrites (upsert is NOT used here by design).
    let mut n: i64 = {
        let mut qc = db
            .conn()
            .query(
                "SELECT COUNT(*) FROM verifications WHERE question_id = ?1",
                (question_id,),
            )
            .await
            .map_err(|e| internal("count", e))?;
        qc.next()
            .await
            .map_err(|e| internal("count-row", e))?
            .map(|r| r.get(0).unwrap_or(0))
            .unwrap_or(0)
    };
    let row = loop {
        n += 1;
        let id = format!("v_{question_id}_{n:04}");
        let mut chk = db
            .conn()
            .query("SELECT id FROM verifications WHERE id = ?1", (id.as_str(),))
            .await
            .map_err(|e| internal("id-check", e))?;
        if chk
            .next()
            .await
            .map_err(|e| internal("id-check-row", e))?
            .is_none()
        {
            break Verification {
                id,
                question_id: question_id.to_string(),
                kind: VerifyKind::Human,
                verdict: Verdict::Pass,
                scope: vec![VerifyCheck::Answer, VerifyCheck::Explanation],
                verifier: verifier.to_string(),
                detail: None,
                content_hash: hash,
                created_at,
            };
        }
    };

    // File first: any gap heals on the next idempotent re-seed.
    append_file_row(data_dir, &row)?;
    db.conn()
        .execute(
            "INSERT INTO verifications(id,question_id,kind,verdict,scope,verifier,detail,content_hash,created_at) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)",
            (
                row.id.as_str(),
                row.question_id.as_str(),
                "human",
                "pass",
                serde_json::to_string(&row.scope).unwrap().as_str(),
                row.verifier.as_str(),
                row.detail.as_deref(),
                row.content_hash.as_str(),
                row.created_at.as_str(),
            ),
        )
        .await
        .map_err(|e| internal("insert", e))?;
    Ok(format!("verified {question_id}"))
}

/// Append one row to `data/verifications.json` with review.py's backup
/// discipline: copy aside, write, re-parse, restore on failure.
fn append_file_row(data_dir: &std::path::Path, row: &Verification) -> Result<(), ApiError> {
    let path = data_dir.join("verifications.json");
    let raw = std::fs::read_to_string(&path).map_err(|e| internal("read-log", e))?;
    let mut rows: Vec<Verification> =
        serde_json::from_str(&raw).map_err(|e| internal("parse-log", e))?;
    rows.push(Verification {
        id: row.id.clone(),
        question_id: row.question_id.clone(),
        kind: row.kind,
        verdict: row.verdict,
        scope: row.scope.clone(),
        verifier: row.verifier.clone(),
        detail: row.detail.clone(),
        content_hash: row.content_hash.clone(),
        created_at: row.created_at.clone(),
    });
    let tmp = std::path::Path::new("tmp");
    std::fs::create_dir_all(tmp).map_err(|e| internal("tmpdir", e))?;
    let backup = tmp.join("verifications.backup.json");
    std::fs::copy(&path, &backup).map_err(|e| internal("backup", e))?;
    let write = || -> Result<(), String> {
        let body = serde_json::to_string_pretty(&rows).map_err(|e| e.to_string())?;
        std::fs::write(&path, format!("{body}\n")).map_err(|e| e.to_string())?;
        let check = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
        let _: Vec<Verification> = serde_json::from_str(&check).map_err(|e| e.to_string())?;
        Ok(())
    };
    if let Err(e) = write() {
        let _ = std::fs::copy(&backup, &path);
        return Err(internal("write-log", format!("{e} — backup restored")));
    }
    Ok(())
}

/// Seconds → ISO, factored for the unit test above.
fn iso_of(secs: u64) -> String {
    let days = (secs / 86_400) as i64;
    let tod = secs % 86_400;
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u64;
    let m = (if mp < 10 { mp + 3 } else { mp - 9 }) as u64;
    let y = (if m <= 2 { y + 1 } else { y }) as u64;
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z",
        tod / 3_600,
        (tod % 3_600) / 60,
        tod % 60
    )
}

#[cfg(test)]
mod tests {
    use super::now_iso_utc;

    #[test]
    fn iso_shape_and_order() {
        let a = now_iso_utc();
        assert_eq!(a.len(), 20, "YYYY-MM-DDTHH:MM:SSZ");
        assert!(a.ends_with('Z'));
        // Fixed vectors via the same civil math, checked against Python
        // datetime (2026-10-14T00:00:00Z == 1791936000).
        assert_eq!(super::iso_of(0), "1970-01-01T00:00:00Z");
        assert_eq!(super::iso_of(1_791_936_000), "2026-10-14T00:00:00Z");
        assert!(super::iso_of(1) > super::iso_of(0));
    }
}
