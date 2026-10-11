//! API keys — operational state, not published content.
//!
//! Separate from `bank/` because the lifecycles differ: keys are issued,
//! revoked and (later) billed; the bank is immutable published content. The file
//! lives outside `data/` and is gitignored, so credential digests never enter the
//! committed constant (D24/D28).
//!
//! v1 scope: CLI-issued, no accounts, no sessions. `account_id` rides along
//! defaulted to `"local"` so Phase 2 (accounts/dashboard) is additive.

mod store;
mod turso;

pub use store::KeyStore;
pub use turso::{ImportReport, TursoKeyStore};

use std::path::Path;
use std::sync::RwLock;

use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

use crate::error::ApiError;

/// Which key store the process runs on. Selected once at boot from config:
/// Turso when `TURSO_DB_URL` + `TURSO_DB_TOKEN` are both set, the gitignored
/// file otherwise (dev, and recovery when Turso is down).
///
/// One backend, one shape for every caller — `auth.rs` and the CLI never know
/// which they got. This is the D23 discipline applied to keys (D53): a Turso
/// impl behind the same seam, file stays fallback forever.
pub enum KeyBackend {
    /// **Test / import-source only — never selected at runtime** (`open_backend`
    /// is Turso-or-error, D53). Kept so tests run without the network and
    /// `key import` has a file to read. Reload-on-resolve behind the lock keeps
    /// the two-process CLI write / test read coherent.
    File(RwLock<KeyStore>),
    /// The live backend. Keys live in Turso.
    Remote(Box<TursoKeyStore>),
}

impl KeyBackend {
    pub fn file(store: KeyStore) -> Self {
        Self::File(RwLock::new(store))
    }

    pub async fn open_remote(url: &str, token: &str, ttl_secs: u64) -> Result<Self, ApiError> {
        Ok(Self::Remote(Box::new(
            TursoKeyStore::open(url, token, ttl_secs).await?,
        )))
    }

    /// Human-readable backend for boot logs: `turso`, or `file:<path>` in tests.
    pub fn describe(&self) -> String {
        match self {
            Self::File(lock) => {
                let path = lock
                    .read()
                    .map(|s| s.path().display().to_string())
                    .unwrap_or_else(|_| "<locked>".into());
                format!("file:{path}")
            }
            Self::Remote(_) => "turso".to_owned(),
        }
    }

    pub async fn resolve(&self, presented: &str) -> Option<ApiKey> {
        match self {
            Self::File(lock) => {
                let mut store = lock.write().ok()?;
                // R1: CLI changes land without a restart; mtime equality is
                // one stat in the common case.
                let _ = store.reload_if_changed();
                store.resolve(presented)
            }
            Self::Remote(r) => r.resolve(presented).await,
        }
    }

    pub async fn count(&self) -> Result<usize, ApiError> {
        match self {
            Self::File(lock) => Ok(lock.read().map_err(|_| poisoned())?.count()),
            Self::Remote(r) => r.count().await,
        }
    }

    pub async fn create(&self, label: &str, rate_limit: u32) -> Result<(ApiKey, String), ApiError> {
        match self {
            Self::File(lock) => lock
                .write()
                .map_err(|_| poisoned())?
                .create(label, rate_limit),
            Self::Remote(r) => r.create(label, rate_limit).await,
        }
    }

    pub async fn list(&self) -> Result<Vec<ApiKey>, ApiError> {
        match self {
            Self::File(lock) => Ok(lock.read().map_err(|_| poisoned())?.list()),
            Self::Remote(r) => r.list().await,
        }
    }

    pub async fn revoke(&self, id: &str) -> Result<bool, ApiError> {
        match self {
            Self::File(lock) => lock.write().map_err(|_| poisoned())?.revoke(id),
            Self::Remote(r) => r.revoke(id).await,
        }
    }

    pub async fn rotate(
        &self,
        id: &str,
        grace_hours: u64,
    ) -> Result<Option<(ApiKey, String)>, ApiError> {
        match self {
            Self::File(lock) => lock
                .write()
                .map_err(|_| poisoned())?
                .rotate(id, grace_hours),
            Self::Remote(r) => r.rotate(id, grace_hours).await,
        }
    }

    /// `key import` — only meaningful file -> Turso; refused otherwise.
    pub async fn import_file(&self, path: &Path, dry_run: bool) -> Result<ImportReport, ApiError> {
        match self {
            Self::File(_) => Err(ApiError::config(
                "key import requires the Turso backend (TURSO_DB_URL + TURSO_DB_TOKEN set)",
            )),
            Self::Remote(r) => {
                let source = KeyStore::open_json(path)?;
                r.import(&source, dry_run).await
            }
        }
    }
}

fn poisoned() -> ApiError {
    ApiError::Internal("key store poisoned".into())
}

fn default_account() -> String {
    "local".to_owned()
}

fn default_plan() -> String {
    "free".to_owned()
}

fn default_scopes() -> String {
    "questions:read reports:write".to_owned()
}

/// A key as stored. Deliberately carries no secret material — no plaintext,
/// no hash. `key_prefix` (first 8 chars of `sk_…`) is for support lookup only
/// and never authenticates.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct ApiKey {
    pub id: String,
    pub label: String,
    #[serde(default = "default_account")]
    pub account_id: String,
    #[serde(default = "default_plan")]
    pub plan: String,
    #[serde(default = "default_scopes")]
    pub scopes: String,
    /// Per-key request allowance (D26) — a column, not a key *type*.
    pub rate_limit: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub quota_monthly: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub key_prefix: Option<String>,
    pub created_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_used_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub suspended_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub suspend_reason: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub revoked_at: Option<String>,
}

/// Lifecycle state, derived — never stored. `Suspended` is reserved for
/// Phase 2 (abuse/billing); v1 ships Active/Revoked/Expired only.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeyStatus {
    Active,
    Suspended,
    Revoked,
    Expired,
}

impl KeyStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Suspended => "suspended",
            Self::Revoked => "revoked",
            Self::Expired => "expired",
        }
    }
}

impl ApiKey {
    pub fn status(&self) -> KeyStatus {
        if self.revoked_at.is_some() {
            return KeyStatus::Revoked;
        }
        if self.suspended_at.is_some() {
            return KeyStatus::Suspended;
        }
        if let Some(exp) = self.expires_at.as_deref() {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0);
            if exp.parse::<u64>().is_ok_and(|e| e <= now) {
                return KeyStatus::Expired;
            }
        }
        KeyStatus::Active
    }

    pub fn is_live(&self) -> bool {
        self.status() == KeyStatus::Active
    }
}
