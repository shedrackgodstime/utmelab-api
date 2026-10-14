//! `TursoKeyStore` — the `api_keys` table in Turso (Phase 1).
//!
//! Remote via `turso_serverless`, matching our `turso://` engine (see
//! `docs/KEY_LIFECYCLE_PLAN.md` §11: `libsql` dropped in D28; local+sync needs
//! push/pull choreography per revoke that buys nothing at one instance).
//! Revoke is globally visible on the next request — cache miss reads the wire;
//! revoke invalidates the cache immediately. Rows are the file's `StoredKey`
//! shape, so `key import` copies columns verbatim.
//!
//! `new(&Db)` borrows the shared connection for scaffolding; `open()` is the
//! runtime path and runs the store-owned `DDL` (no migrations yet).

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use turso_serverless::Connection;

use super::store::{StoredKey, generate_key, hash_key, new_id, now_iso, now_secs, prefix_of};
use super::{ApiKey, KeyStore};
use crate::db::Db;
use crate::error::ApiError;

/// Columns in `StoredKey` field order. One place: SELECT, INSERT, row mapping.
const COLUMNS: &str = "id, key_hash, key_prefix, label, account_id, plan, scopes, rate_limit, quota_monthly, created_at, last_used_at, expires_at, suspended_at, suspend_reason, revoked_at";

/// Owned by this store until its migration phase lands. Runs on `open()` via
/// `execute_batch` — idempotent (`IF NOT EXISTS`), so restarts re-apply safely.
const DDL: &str = "CREATE TABLE IF NOT EXISTS api_keys (
    id            TEXT PRIMARY KEY,
    key_hash      TEXT NOT NULL UNIQUE,
    key_prefix    TEXT,
    label         TEXT NOT NULL,
    account_id    TEXT NOT NULL DEFAULT 'local',
    plan          TEXT NOT NULL DEFAULT 'free',
    scopes        TEXT NOT NULL DEFAULT 'questions:read reports:write',
    rate_limit    INTEGER NOT NULL,
    quota_monthly INTEGER,
    created_at    TEXT NOT NULL,
    last_used_at  TEXT,
    expires_at    TEXT,
    suspended_at  TEXT,
    suspend_reason TEXT,
    revoked_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_keys_account ON api_keys(account_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);";

pub struct TursoKeyStore {
    conn: Connection,
    /// How long a resolved key stays cached before the wire is consulted.
    ttl: Duration,
    /// hash -> (key, fetched-at). Unknown keys are NOT negatively cached: a
    /// typo'd key may hammer the wire, but a negative cache could swallow a
    /// just-issued key for a whole TTL.
    cache: Mutex<HashMap<String, (ApiKey, Instant)>>,
}

fn internal(context: &str, e: impl std::fmt::Display) -> ApiError {
    ApiError::Internal(format!("{context}: {e}"))
}

impl TursoKeyStore {
    /// Wrap the shared connection. The table is created on `open()` from the
    /// store-owned `DDL` above — never by `Db`, until migrations land.
    pub fn new(db: &Db, ttl_secs: u64) -> Self {
        Self {
            conn: db.conn(),
            ttl: Duration::from_secs(ttl_secs),
            cache: Mutex::new(HashMap::new()),
        }
    }

    /// Connect + create table if absent + wrap. The runtime path today;
    /// `serve` builds one `Db` and this runs the store's own DDL over it.
    pub async fn open(url: &str, token: &str, ttl_secs: u64) -> Result<Self, ApiError> {
        let db = Db::connect(url, token).await?;
        db.conn()
            .execute_batch(DDL)
            .await
            .map_err(|e| internal("turso ddl", e))?;
        Ok(Self::new(&db, ttl_secs))
    }

    fn invalidate(&self) {
        if let Ok(mut cache) = self.cache.lock() {
            cache.clear();
        }
    }

    async fn row_to_key(&self, row: &turso_serverless::Row) -> Result<ApiKey, ApiError> {
        Ok(ApiKey {
            id: row.get(0).map_err(|e| internal("row id", e))?,
            label: row.get(3).map_err(|e| internal("row label", e))?,
            account_id: row.get(4).map_err(|e| internal("row account", e))?,
            plan: row.get(5).map_err(|e| internal("row plan", e))?,
            scopes: row.get(6).map_err(|e| internal("row scopes", e))?,
            rate_limit: row.get(7).map_err(|e| internal("row rate", e))?,
            quota_monthly: row.get(8).map_err(|e| internal("row quota", e))?,
            key_prefix: row.get(2).map_err(|e| internal("row prefix", e))?,
            created_at: row.get(9).map_err(|e| internal("row created", e))?,
            last_used_at: row.get(10).map_err(|e| internal("row last_used", e))?,
            expires_at: row.get(11).map_err(|e| internal("row expires", e))?,
            suspended_at: row.get(12).map_err(|e| internal("row suspended", e))?,
            suspend_reason: row.get(13).map_err(|e| internal("row suspend_reason", e))?,
            revoked_at: row.get(14).map_err(|e| internal("row revoked", e))?,
        })
    }

    /// Resolve a presented key: cache first, wire second, live only.
    /// Unknown / revoked / suspended / expired are all `None` (D53).
    pub async fn resolve(&self, presented: &str) -> Option<ApiKey> {
        let hash = hash_key(presented);

        if let Ok(cache) = self.cache.lock() {
            if let Some((key, at)) = cache.get(&hash) {
                if at.elapsed() <= self.ttl && key.is_live() {
                    return Some(key.clone());
                }
            }
        }

        let sql = format!("SELECT {COLUMNS} FROM api_keys WHERE key_hash = ?1");
        let mut rows = self.conn.query(&sql, (hash.as_str(),)).await.ok()?;
        let row = rows.next().await.ok()??;
        let key = self.row_to_key(&row).await.ok()?;
        if !key.is_live() {
            return None;
        }
        if let Ok(mut cache) = self.cache.lock() {
            cache.insert(hash, (key.clone(), Instant::now()));
        }
        Some(key)
    }

    pub async fn count(&self) -> Result<usize, ApiError> {
        let mut rows = self
            .conn
            .query("SELECT COUNT(*) FROM api_keys", ())
            .await
            .map_err(|e| internal("turso count", e))?;
        match rows.next().await.map_err(|e| internal("turso count", e))? {
            Some(r) => r
                .get::<u64>(0)
                .map(|n| n as usize)
                .map_err(|e| internal("row count", e)),
            None => Ok(0),
        }
    }

    pub async fn create(&self, label: &str, rate_limit: u32) -> Result<(ApiKey, String), ApiError> {
        let plaintext = generate_key();
        let record = StoredKey {
            id: new_id(),
            key_hash: hash_key(&plaintext),
            label: label.to_owned(),
            account_id: "local".to_owned(),
            plan: "free".to_owned(),
            scopes: "questions:read reports:write".to_owned(),
            rate_limit,
            quota_monthly: None,
            key_prefix: Some(prefix_of(&plaintext)),
            created_at: now_iso(),
            last_used_at: None,
            expires_at: None,
            suspended_at: None,
            suspend_reason: None,
            revoked_at: None,
        };
        self.insert(&record).await?;
        Ok((record.to_api_key(), plaintext))
    }

    async fn insert(&self, k: &StoredKey) -> Result<(), ApiError> {
        let sql = format!(
            "INSERT INTO api_keys ({COLUMNS}) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15)"
        );
        self.conn
            .execute(
                &sql,
                (
                    k.id.as_str(),
                    k.key_hash.as_str(),
                    k.key_prefix.as_deref(),
                    k.label.as_str(),
                    k.account_id.as_str(),
                    k.plan.as_str(),
                    k.scopes.as_str(),
                    k.rate_limit,
                    k.quota_monthly,
                    k.created_at.as_str(),
                    k.last_used_at.as_deref(),
                    k.expires_at.as_deref(),
                    k.suspended_at.as_deref(),
                    k.suspend_reason.as_deref(),
                    k.revoked_at.as_deref(),
                ),
            )
            .await
            .map_err(|e| internal("turso insert", e))?;
        Ok(())
    }

    pub async fn list(&self) -> Result<Vec<ApiKey>, ApiError> {
        let sql = format!("SELECT {COLUMNS} FROM api_keys ORDER BY rowid");
        let mut rows = self
            .conn
            .query(&sql, ())
            .await
            .map_err(|e| internal("turso list", e))?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().await.map_err(|e| internal("turso list", e))? {
            out.push(self.row_to_key(&row).await?);
        }
        Ok(out)
    }

    pub async fn revoke(&self, id: &str) -> Result<bool, ApiError> {
        let changed = self
            .conn
            .execute(
                "UPDATE api_keys SET revoked_at = ?1 WHERE id = ?2 AND revoked_at IS NULL",
                (now_iso(), id),
            )
            .await
            .map_err(|e| internal("turso revoke", e))?;
        if changed > 0 {
            self.invalidate();
        }
        Ok(changed > 0)
    }

    /// Same semantics as the file store: successor inherits label + plan, old
    /// key's `expires_at` becomes now + grace, old plaintext never touched.
    pub async fn rotate(
        &self,
        id: &str,
        grace_hours: u64,
    ) -> Result<Option<(ApiKey, String)>, ApiError> {
        let sql = format!("SELECT {COLUMNS} FROM api_keys WHERE id = ?1");
        let mut rows = self
            .conn
            .query(&sql, (id,))
            .await
            .map_err(|e| internal("turso rotate", e))?;
        let Some(row) = rows.next().await.map_err(|e| internal("turso rotate", e))? else {
            return Ok(None);
        };
        let old = self.row_to_key(&row).await?;
        if old.revoked_at.is_some() {
            return Ok(None);
        }

        let plaintext = generate_key();
        let successor = StoredKey {
            id: new_id(),
            key_hash: hash_key(&plaintext),
            label: old.label.clone(),
            account_id: old.account_id.clone(),
            plan: old.plan.clone(),
            scopes: old.scopes.clone(),
            rate_limit: old.rate_limit,
            quota_monthly: old.quota_monthly,
            key_prefix: Some(prefix_of(&plaintext)),
            created_at: now_iso(),
            last_used_at: None,
            expires_at: None,
            suspended_at: None,
            suspend_reason: None,
            revoked_at: None,
        };

        let expires = (now_secs() + grace_hours.saturating_mul(3600)).to_string();
        self.conn
            .execute(
                "UPDATE api_keys SET expires_at = ?1 WHERE id = ?2",
                (expires, old.id.as_str()),
            )
            .await
            .map_err(|e| internal("turso rotate", e))?;
        self.insert(&successor).await?;
        self.invalidate();
        Ok(Some((successor.to_api_key(), plaintext)))
    }

    /// One-time file -> Turso migration. Rows already present (by id) are
    /// skipped and counted, never overwritten; malformed rows refused with a
    /// reason. Every refusal counted — a silent drop reads as a bug (D51 rule).
    pub async fn import(&self, source: &KeyStore, dry_run: bool) -> Result<ImportReport, ApiError> {
        let mut report = ImportReport::default();
        for row in source.stored() {
            report.total += 1;
            if row.id.is_empty() || row.key_hash.is_empty() || row.label.is_empty() {
                report.refused += 1;
                report
                    .refusals
                    .push(format!("{}: missing id, hash or label", row.id));
                continue;
            }
            if self.row_exists(&row.id).await? {
                report.skipped += 1;
                report.skips.push(format!("{}: already present", row.id));
                continue;
            }
            if !dry_run {
                self.insert(row).await?;
            }
            report.inserted += 1;
        }
        if !dry_run {
            self.invalidate();
        }
        Ok(report)
    }

    async fn row_exists(&self, id: &str) -> Result<bool, ApiError> {
        let mut rows = self
            .conn
            .query("SELECT id FROM api_keys WHERE id = ?1", (id,))
            .await
            .map_err(|e| internal("turso exists", e))?;
        Ok(rows
            .next()
            .await
            .map_err(|e| internal("turso exists", e))?
            .is_some())
    }
}

/// What `key import` did, itemised. Printed whether it ran or dry-ran.
#[derive(Debug, Default)]
pub struct ImportReport {
    pub total: usize,
    pub inserted: usize,
    pub skipped: usize,
    pub refused: usize,
    pub skips: Vec<String>,
    pub refusals: Vec<String>,
}
