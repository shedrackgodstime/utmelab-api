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
use crate::error::ApiError;

#[derive(Clone, Debug, Serialize, Deserialize)]
struct StoredKey {
    id: String,
    key_hash: String,
    label: String,
    rate_limit: u32,
    created_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    revoked_at: Option<String>,
}

impl StoredKey {
    fn to_api_key(&self) -> ApiKey {
        ApiKey {
            id: self.id.clone(),
            label: self.label.clone(),
            rate_limit: self.rate_limit,
            created_at: self.created_at.clone(),
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

        Ok(Self { path, file, index })
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
        let hash = hash_key(&plaintext);

        let record = StoredKey {
            id: new_id(),
            key_hash: hash.clone(),
            label: label.to_owned(),
            rate_limit,
            created_at: now_iso(),
            revoked_at: None,
        };

        self.persist(record.clone())?;
        Ok((record.to_api_key(), plaintext))
    }

    /// Resolve a presented key. `None` for unknown **or** revoked.
    pub fn resolve(&self, presented: &str) -> Option<ApiKey> {
        let hash = hash_key(presented);
        self.index
            .get(&hash)
            .filter(|k| k.revoked_at.is_none())
            .map(StoredKey::to_api_key)
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
        self.persist(record)?;
        Ok(true)
    }

    fn persist(&mut self, record: StoredKey) -> Result<(), ApiError> {
        match self.file.keys.iter_mut().find(|k| k.id == record.id) {
            Some(existing) => *existing = record.clone(),
            None => self.file.keys.push(record.clone()),
        }

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

        self.index.insert(record.key_hash.clone(), record);
        Ok(())
    }
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
fn generate_key() -> String {
    let mut bytes = [0u8; 32];
    rand::rng().fill(&mut bytes);
    format!("sk_{}", hex(&bytes))
}

fn hash_key(key: &str) -> String {
    hex(&Sha256::digest(key.as_bytes()))
}

fn new_id() -> String {
    let mut bytes = [0u8; 16];
    rand::rng().fill(&mut bytes);
    format!("key_{}", hex(&bytes))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Seconds-resolution UTC. Good enough for a credential lifecycle timestamp and
/// keeps the dependency list short.
fn now_iso() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    secs.to_string()
}
