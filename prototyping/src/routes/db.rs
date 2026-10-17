use std::time::Instant;

use axum::{extract::State, http::StatusCode, Json};
use serde::Serialize;

use crate::state::DbOnly;

#[derive(Serialize)]
pub struct DbResult {
    pub mode: &'static str,
    pub tables: usize,
    pub elapsed_ms: u64,
}

fn gate(s: &DbOnly) -> Result<tokio::sync::OwnedSemaphorePermit, (StatusCode, String)> {
    s.db_gate.clone().try_acquire_owned().map_err(|_| {
        (
            StatusCode::SERVICE_UNAVAILABLE,
            "db saturated, retry".to_string(),
        )
    })
}

pub async fn db_remote(State(s): State<DbOnly>) -> Result<Json<DbResult>, (StatusCode, String)> {
    let db = s.db_remote.as_ref().ok_or((
        StatusCode::SERVICE_UNAVAILABLE,
        "no remote db configured".into(),
    ))?;
    let _permit = gate(&s)?;
    let start = Instant::now();
    let conn = db.connect().map_err(|e| internal(e.to_string()))?;
    let mut rows = conn
        .query(
            "SELECT name FROM sqlite_master WHERE type='table' LIMIT 20",
            (),
        )
        .await
        .map_err(|e| internal(e.to_string()))?;
    let mut n = 0;
    while rows
        .next()
        .await
        .map_err(|e| internal(e.to_string()))?
        .is_some()
    {
        n += 1;
    }
    Ok(Json(DbResult {
        mode: "remote",
        tables: n,
        elapsed_ms: start.elapsed().as_millis() as u64,
    }))
}

pub async fn db_sync(State(s): State<DbOnly>) -> Result<Json<DbResult>, (StatusCode, String)> {
    let db = s.db_sync.as_ref().ok_or((
        StatusCode::SERVICE_UNAVAILABLE,
        "no sync db configured".into(),
    ))?;
    let _permit = gate(&s)?;
    let start = Instant::now();
    let conn = db.connect().await.map_err(|e| internal(e.to_string()))?;
    let mut rows = conn
        .query(
            "SELECT name FROM sqlite_master WHERE type='table' LIMIT 20",
            (),
        )
        .await
        .map_err(|e| internal(e.to_string()))?;
    let mut n = 0;
    while rows
        .next()
        .await
        .map_err(|e| internal(e.to_string()))?
        .is_some()
    {
        n += 1;
    }
    Ok(Json(DbResult {
        mode: "sync",
        tables: n,
        elapsed_ms: start.elapsed().as_millis() as u64,
    }))
}

fn internal(msg: String) -> (StatusCode, String) {
    (StatusCode::BAD_GATEWAY, msg)
}
