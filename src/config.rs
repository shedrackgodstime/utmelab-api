//! Process configuration, read once from the environment.
//!
//! Everything has a working default so the service boots during development
//! without ceremony. The key file is the one value worth being deliberate about:
//! it must live outside the committed constant, because it holds credential
//! digests.

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

        Ok(Self {
            bind,
            keys_file,
            reports_file,
            default_rate_limit,
            data_dir,
        })
    }
}
