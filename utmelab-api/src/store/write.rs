//! Single write path. Execute plus push under one mutex that the pull
//! loop also holds, so a pull can never interleave (and discard) an
//! unpushed local write. Callers get the affected-row count; push failure
//! is upstream — local row exists, cloud lags until the next push.

use super::{gate, synced, upstream};
use crate::{error::AppError, state::DbState};

pub async fn execute_write(
    s: &DbState,
    sql: &str,
    params: Vec<turso::Value>,
) -> Result<u64, AppError> {
    let _permit = gate(s)?;
    let _w = s.write_mutex.lock().await;
    let db = synced(s).await?;
    let conn = s.conns.take(&db).await?;
    let result = execute_and_verify(&conn, sql, params).await;
    s.conns.put(conn).await;
    let n = result?;
    db.push().await.map_err(upstream)?;
    Ok(n)
}

/// DDL twin of [`execute_write`]. `changes()` is meaningless for schema
/// statements, so no visibility check — failure still surfaces as Err.
pub async fn execute_ddl(s: &DbState, sql: &str) -> Result<(), AppError> {
    let _permit = gate(s)?;
    let _w = s.write_mutex.lock().await;
    let db = synced(s).await?;
    let conn = s.conns.take(&db).await?;
    let result = conn.execute(sql, ()).await.map_err(upstream);
    s.conns.put(conn).await;
    result?;
    db.push().await.map_err(upstream)?;
    Ok(())
}

/// Execute then confirm the row count is visible on the same connection.
async fn execute_and_verify(
    conn: &turso::Connection,
    sql: &str,
    params: Vec<turso::Value>,
) -> Result<u64, AppError> {
    let n = conn.execute(sql, params).await.map_err(upstream)?;
    let seen: i64 = conn
        .query("SELECT changes()", ())
        .await
        .map_err(upstream)?
        .next()
        .await
        .map_err(upstream)?
        .and_then(|r| r.get(0).ok())
        .unwrap_or(0);
    if seen != n as i64 {
        return Err(AppError::Upstream("write not visible".to_string()));
    }
    Ok(n)
}
