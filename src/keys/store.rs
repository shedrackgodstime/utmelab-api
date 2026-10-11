//! API key store — behind a trait so the backing store can change without
//! touching routes or auth (D23 discipline, applied to keys).
//!
//! Today: `JsonKeyStore`, a local file **outside** the committed constant.
//! Later: a Turso-backed impl. That is not written yet, deliberately — it will be
//! built against the documented client, not reverse-engineered.
//!
//! The plaintext key is generated, returned **once**, and never stored. Only its
//! SHA-256 digest is persisted (D27), so reading the file does not hand over
//! working credentials.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use rand::Rng;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::ApiKey;
use super::{default_account, default_plan, default_scopes};
use crate::error::ApiError;

/// One row of the single `api_keys` table — file and Turso both store exactly
/// this shape, so migration is column-for-column with no mapping layer.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct StoredKey {
    pub(super) id: String,
    pub(super) key_hash: String,
    pub(super) label: String,
    /// Owner. Always `"local"` in v1 (no accounts) — the column exists so
    /// Phase 2 is additive, not a migration.
    #[serde(default = "default_account")]
    pub(super) account_id: String,
    #[serde(default = "default_plan")]
    pub(super) plan: String,
    #[serde(default = "default_scopes")]
    pub(super) scopes: String,
    pub(super) rate_limit: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(super) quota_monthly: Option<u32>,
    /// First 11 chars of the plaintext (`sk_` + 8 hex). Support lookup only —
    /// never authenticates.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(super) key_prefix: Option<String>,
    pub(super) created_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(super) last_used_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(super) expires_at: Option<String>,
    /// Reserved for Phase 2 (abuse/billing). No v1 writer.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(super) suspended_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(super) suspend_reason: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(super) revoked_at: Option<String>,
}

impl StoredKey {
    pub(super) fn to_api_key(&self) -> ApiKey {
        ApiKey {
            id: self.id.clone(),
            label: self.label.clone(),
            account_id: self.account_id.clone(),
            plan: self.plan.clone(),
            scopes: self.scopes.clone(),
            rate_limit: self.rate_limit,
            quota_monthly: self.quota_monthly,
            key_prefix: self.key_prefix.clone(),
            created_at: self.created_at.clone(),
            last_used_at: self.last_used_at.clone(),
            expires_at: self.expires_at.clone(),
            suspended_at: self.suspended_at.clone(),
            suspend_reason: self.suspend_reason.clone(),
            revoked_at: self.revoked_at.clone(),
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct KeyFile {
    #[serde(default)]
    keys: Vec<StoredKey>,
}

/// The JSON implementation of the key store. An unknown key and a revoked key
/// must be indistinguishable to callers — never let them tell the two apart.
///
/// This struct *is* that implementation. When the Turso store arrives it
/// becomes one of several impls behind the same shape (D23), and everything in
/// `auth.rs` and `routes.rs` stays exactly as it is.
#[derive(Clone, Debug)]
pub struct KeyStore {
    path: PathBuf,
    file: KeyFile,
    /// Index by digest so resolution is a lookup, not a scan.
    index: HashMap<String, StoredKey>,
    /// mtime at last load — backing for [`KeyStore::reload_if_changed`] (R1).
    /// The CLI rewrites this file from another process; the server must see it
    /// without a restart.
    loaded_mtime: Option<std::time::SystemTime>,
}

impl KeyStore {
    /// Open a JSON-backed store, creating the file (and its directory) if absent.
    pub fn open_json(path: impl AsRef<Path>) -> Result<Self, ApiError> {
        let path = path.as_ref().to_path_buf();

        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent)
                .map_err(|e| ApiError::Internal(format!("create {}: {e}", parent.display())))?;
        }

        let file = match std::fs::read(&path) {
            Ok(bytes) => serde_json::from_slice(&bytes)
                .map_err(|e| ApiError::Internal(format!("{} is corrupt: {e}", path.display())))?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => KeyFile::default(),
            Err(e) => return Err(ApiError::Internal(format!("read {}: {e}", path.display()))),
        };

        let index = file
            .keys
            .iter()
            .map(|k| (k.key_hash.clone(), k.clone()))
            .collect();

        Ok(Self {
            path: path.clone(),
            file,
            index,
            loaded_mtime: mtime_of(&path),
        })
    }

    /// Re-read the file if another process (the CLI) changed it since we
    /// loaded. Returns true when state was refreshed. A missing file keeps the
    /// last known keys — cached live keys fail open, unknown keys fail closed.
    pub fn reload_if_changed(&mut self) -> Result<bool, ApiError> {
        let current = mtime_of(&self.path);
        if current == self.loaded_mtime {
            return Ok(false);
        }
        let bytes = match std::fs::read(&self.path) {
            Ok(b) => b,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(e) => {
                return Err(ApiError::Internal(format!(
                    "read {}: {e}",
                    self.path.display()
                )));
            }
        };
        let file: KeyFile = serde_json::from_slice(&bytes)
            .map_err(|e| ApiError::Internal(format!("{} is corrupt: {e}", self.path.display())))?;
        self.index = file
            .keys
            .iter()
            .map(|k| (k.key_hash.clone(), k.clone()))
            .collect();
        self.file = file;
        self.loaded_mtime = current;
        Ok(true)
    }

    pub fn count(&self) -> usize {
        self.index.len()
    }

    /// Where this store persists. Useful for logging and for reopening it.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Issue a key. Returns the record and the **plaintext key**, which the
    /// caller must display once and must never log.
    pub fn create(&mut self, label: &str, rate_limit: u32) -> Result<(ApiKey, String), ApiError> {
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

        self.upsert(record.clone());
        self.save()?;
        Ok((record.to_api_key(), plaintext))
    }

    /// Every key, insertion order, including revoked and expired — owner
    /// visibility for the CLI. Never carries secret material by construction
    /// (see `ApiKey`: no plaintext, no hash).
    pub fn list(&self) -> Vec<ApiKey> {
        self.file.keys.iter().map(StoredKey::to_api_key).collect()
    }

    /// Raw rows, for `key import` (file -> Turso). Same shape the table holds,
    /// so migration copies columns verbatim — hashes included, plaintext never
    /// existed here to copy.
    pub(super) fn stored(&self) -> &[StoredKey] {
        &self.file.keys
    }

    /// Resolve a presented key. `None` for unknown, revoked, suspended **or**
    /// expired — callers must never distinguish them.
    pub fn resolve(&self, presented: &str) -> Option<ApiKey> {
        let hash = hash_key(presented);
        self.index
            .get(&hash)
            .map(StoredKey::to_api_key)
            .filter(|k| k.is_live())
    }

    /// Rotate a key: a successor is issued with the same label and rate limit,
    /// and the old key expires after `grace_hours`. Returns `None` when no
    /// live key carries `id`. The old plaintext is untouched — only the new
    /// one is ever shown.
    pub fn rotate(
        &mut self,
        id: &str,
        grace_hours: u64,
    ) -> Result<Option<(ApiKey, String)>, ApiError> {
        let Some(existing) = self.index.values().find(|k| k.id == id).cloned() else {
            return Ok(None);
        };
        if existing.revoked_at.is_some() {
            return Ok(None);
        }

        let plaintext = generate_key();
        let successor = StoredKey {
            id: new_id(),
            key_hash: hash_key(&plaintext),
            label: existing.label.clone(),
            account_id: existing.account_id.clone(),
            plan: existing.plan.clone(),
            scopes: existing.scopes.clone(),
            rate_limit: existing.rate_limit,
            quota_monthly: existing.quota_monthly,
            key_prefix: Some(prefix_of(&plaintext)),
            created_at: now_iso(),
            last_used_at: None,
            expires_at: None,
            suspended_at: None,
            suspend_reason: None,
            revoked_at: None,
        };

        let mut old = existing;
        old.expires_at = Some((now_secs() + grace_hours.saturating_mul(3600)).to_string());

        self.upsert(old);
        self.upsert(successor.clone());
        self.save()?;
        Ok(Some((successor.to_api_key(), plaintext)))
    }

    pub fn revoke(&mut self, id: &str) -> Result<bool, ApiError> {
        let Some(existing) = self.index.values().find(|k| k.id == id).cloned() else {
            return Ok(false);
        };
        if existing.revoked_at.is_some() {
            return Ok(false);
        }

        let mut record = existing;
        record.revoked_at = Some(now_iso());
        self.upsert(record);
        self.save()?;
        Ok(true)
    }

    fn upsert(&mut self, record: StoredKey) {
        match self.file.keys.iter_mut().find(|k| k.id == record.id) {
            Some(existing) => *existing = record.clone(),
            None => self.file.keys.push(record.clone()),
        }
        self.index.insert(record.key_hash.clone(), record);
    }

    fn save(&mut self) -> Result<(), ApiError> {
        // Write-then-rename: a crash mid-write must not truncate the only copy
        // of the credentials.
        let bytes = serde_json::to_vec_pretty(&self.file)
            .map_err(|e| ApiError::Internal(format!("serialise keys: {e}")))?;
        let tmp = self.path.with_extension("json.tmp");

        std::fs::write(&tmp, &bytes)
            .map_err(|e| ApiError::Internal(format!("write {}: {e}", tmp.display())))?;
        restrict_permissions(&tmp)?;
        std::fs::rename(&tmp, &self.path)
            .map_err(|e| ApiError::Internal(format!("rename into {}: {e}", self.path.display())))?;

        self.loaded_mtime = mtime_of(&self.path);
        Ok(())
    }
}

/// mtime of a path, or None when it has none (missing file, coarse FS).
/// Equality is all we need: changed or not.
fn mtime_of(path: &Path) -> Option<std::time::SystemTime> {
    std::fs::metadata(path).and_then(|m| m.modified()).ok()
}

/// Best effort: the file holds credential digests, so keep it owner-only.
/// Not fatal — a filesystem without POSIX modes is not a reason to refuse boot.
fn restrict_permissions(path: &Path) -> Result<(), ApiError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let perms = std::fs::Permissions::from_mode(0o600);
        std::fs::set_permissions(path, perms)
            .map_err(|e| ApiError::Internal(format!("chmod {}: {e}", path.display())))?;
    }
    #[cfg(not(unix))]
    let _ = path;
    Ok(())
}

/// `sk_` + 32 random bytes as hex — 256 bits of entropy.
pub(super) fn generate_key() -> String {
    let mut bytes = [0u8; 32];
    rand::rng().fill(&mut bytes);
    format!("sk_{}", hex(&bytes))
}

pub(super) fn hash_key(key: &str) -> String {
    hex(&Sha256::digest(key.as_bytes()))
}

/// First 11 chars of the plaintext (`sk_` + 8 hex) for support lookup.
/// Never authenticates — the hash does that.
pub(super) fn prefix_of(plaintext: &str) -> String {
    plaintext.chars().take(11).collect()
}

pub(super) fn new_id() -> String {
    let mut bytes = [0u8; 16];
    rand::rng().fill(&mut bytes);
    format!("key_{}", hex(&bytes))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Seconds-resolution UTC. Good enough for a credential lifecycle timestamp and
/// keeps the dependency list short. Also the unit of `expires_at`, so
/// [`ApiKey::status`] can compare without parsing dates.
pub(super) fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

pub(super) fn now_iso() -> String {
    now_secs().to_string()
}
