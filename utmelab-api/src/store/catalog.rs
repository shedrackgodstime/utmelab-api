//! Gated local reads. Every function here holds a gate permit for its
//! duration and retries transient lock contention, so bursts degrade to
//! fast 503s instead of wedging workers.

use super::{upstream, with_conn};
use crate::{core, error::AppError, state::DbState};

pub async fn fetch_table_names(s: &DbState) -> Result<Vec<String>, AppError> {
    with_conn(s, |conn| async move {
        let mut rows = conn
            .query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'turso_%' LIMIT 50",
                (),
            )
            .await
            .map_err(upstream)?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().await.map_err(upstream)? {
            let name: String = row.get(0).map_err(upstream)?;
            out.push(name);
        }
        Ok(out)
    })
    .await
}

/// Single composer for "list local tables". Both `api` and `mcp` call this;
/// the mapping itself stays in `core` so surfaces never duplicate it.
pub async fn table_refs(s: &DbState) -> Result<Vec<core::models::TableRef>, AppError> {
    Ok(core::catalog::to_refs(fetch_table_names(s).await?))
}

pub async fn fetch_rows(
    s: &DbState,
    table: &str,
    limit: u64,
) -> Result<crate::core::models::RowPage, AppError> {
    if !core::validate::ident(table) {
        return Err(AppError::BadRequest("bad table name".to_string()));
    }
    let limit = limit.clamp(1, 100);
    let table = table.to_string();
    with_conn(s, |conn| {
        let table = table.clone();
        async move {
            let sql = format!("SELECT * FROM \"{table}\" LIMIT {limit}");
            let mut rows = conn.query(&sql, ()).await.map_err(upstream)?;
            let mut out: Vec<Vec<String>> = Vec::new();
            let mut width = 0;
            while let Some(row) = rows.next().await.map_err(upstream)? {
                width = row.column_count();
                let mut r = Vec::with_capacity(width);
                for i in 0..width {
                    let v = row.get_value(i).map_err(upstream)?;
                    r.push(match v {
                        turso::Value::Null => String::from("null"),
                        turso::Value::Text(t) => t,
                        turso::Value::Integer(n) => n.to_string(),
                        turso::Value::Real(f) => f.to_string(),
                        turso::Value::Blob(b) => format!("<{} bytes>", b.len()),
                    });
                }
                out.push(r);
            }
            Ok(crate::core::models::RowPage {
                cols: (0..width).map(|i| format!("c{i}")).collect(),
                rows: out,
            })
        }
    })
    .await
}
