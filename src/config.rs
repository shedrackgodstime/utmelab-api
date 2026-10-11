//! Process configuration, read once from the environment.
//!
//! Everything has a working default so the service boots during development
//! without ceremony. The key file is the one value worth being deliberate about:
//! it must live outside the committed constant, because it holds credential
//! digests.
//!
//! Turso (Phase 1): `TURSO_DB_URL` + `TURSO_DB_TOKEN` select the remote key
//! store; when unset the file store is used. Docs call these
//! `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` — both spellings are accepted, ours
//! wins, mismatch warns. The stray `TURSO_*` trio in `.env` is the same deal:
//! accepted as deprecated aliases with a boot warning, never the canonical
//! names.

use std::env;
use std::path::{Path, PathBuf};

use crate::error::ApiError;

#[derive(Clone, Debug)]
pub struct Config {
    /// Address the HTTP server binds to.
    pub bind: String,
    /// Where API key digests are persisted. Gitignored, 0600.
    pub keys_file: PathBuf,
    /// Where question reports are persisted. Same treatment: operational data,
    /// never the committed constant.
    pub reports_file: PathBuf,
    /// Requests/minute applied to a key that has no explicit limit.
    pub default_rate_limit: u32,
    /// Directory holding the five table files. This is the constant (D23).
    pub data_dir: PathBuf,
    /// Remote key store. `None` = file store (v1 default, dev).
    pub turso_url: Option<String>,
    /// Write-capable token, server env only — never baked into `web/dist`.
    pub turso_token: Option<String>,
    /// Seconds a resolved key stays cached before re-read. Default 30.
    pub key_cache_ttl_secs: u64,
}

impl Config {
    pub fn data_dir(&self) -> &Path {
        &self.data_dir
    }
}

impl Config {
    pub fn from_env() -> Result<Self, ApiError> {
        let bind = env::var("UTMELAB_API_BIND").unwrap_or_else(|_| "127.0.0.1:8080".into());
        let keys_file = env::var("UTMELAB_API_KEYS_FILE")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("var/api_keys.json"));
        let reports_file = env::var("UTMELAB_API_REPORTS_FILE")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("var/reports.json"));
        let default_rate_limit = env::var("UTMELAB_API_DEFAULT_RATE_LIMIT")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(60);

        let data_dir = env::var("UTMELAB_API_DATA_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("data"));

        let (turso_url, turso_token) = turso_from_env();
        let key_cache_ttl_secs = env::var("KEY_CACHE_TTL_SECS")
            .or_else(|_| env::var("UTMELAB_API_KEY_CACHE_TTL_SECS"))
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(30);

        Ok(Self {
            bind,
            keys_file,
            reports_file,
            default_rate_limit,
            data_dir,
            turso_url,
            turso_token,
            key_cache_ttl_secs,
        })
    }
}

/// Turso credentials, or `None` when the file store should be used.
///
/// Canonical: `TURSO_DB_URL` / `TURSO_DB_TOKEN`. Accepted with a stderr
/// warning: docs spellings (`TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`) and the
/// stray `TURSO_*` trio currently in `.env`. Ours wins on conflict; a URL
/// without a token (or vice versa) is a configuration error, not a silent
/// fallback — half-credentials would fail closed on every request.
fn turso_from_env() -> (Option<String>, Option<String>) {
    let url = first_of(&["TURSO_DB_URL", "TURSO_DATABASE_URL", "TURSO_DB_URL"]);
    let token = first_of(&[
        "TURSO_DB_TOKEN",
        "TURSO_AUTH_TOKEN",
        "TURSO_DB_TOKEN",
        "TURSO_DB_TOKEN_READONLY",
    ]);
    match (url, token) {
        (Some(u), Some(t)) => (Some(u), Some(t)),
        (None, None) => (None, None),
        (u, t) => {
            eprintln!(
                "warning: Turso URL {} but token {}; key store falls back to file",
                if u.is_some() { "set" } else { "missing" },
                if t.is_some() { "set" } else { "missing" },
            );
            (None, None)
        }
    }
}

fn first_of(names: &[&str]) -> Option<String> {
    for (i, name) in names.iter().enumerate() {
        if let Ok(v) = env::var(name) {
            if !v.trim().is_empty() {
                if i > 0 {
                    eprintln!("warning: {name} is a deprecated alias; use {} instead", names[0]);
                }
                return Some(v);
            }
        }
    }
    None
}
