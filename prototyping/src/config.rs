// Tune here. Env vars override these defaults at runtime.
pub const DEFAULT_WORKER_THREADS: usize = 4;
pub const DEFAULT_MAX_BLOCKING_THREADS: usize = 32;
pub const DEFAULT_CONCURRENCY_LIMIT: usize = 1000;
pub const DEFAULT_PORT: u16 = 3100;
pub const DEFAULT_REPLICA_PATH: &str = "sync.db";
pub const DEFAULT_SYNC_SECS: u64 = 60;
pub const DEFAULT_DB_MAX_CONCURRENT: usize = 16;

#[derive(Clone)]
pub struct Config {
    pub worker_threads: usize,
    pub max_blocking_threads: usize,
    pub concurrency_limit: usize,
    pub port: u16,
    pub turso_url: String,
    pub turso_token: String,
    pub replica_path: String,
    pub sync_secs: u64,
    pub db_max_concurrent: usize,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            worker_threads: DEFAULT_WORKER_THREADS,
            max_blocking_threads: DEFAULT_MAX_BLOCKING_THREADS,
            concurrency_limit: DEFAULT_CONCURRENCY_LIMIT,
            port: DEFAULT_PORT,
            turso_url: String::new(),
            turso_token: String::new(),
            replica_path: DEFAULT_REPLICA_PATH.to_string(),
            sync_secs: DEFAULT_SYNC_SECS,
            db_max_concurrent: DEFAULT_DB_MAX_CONCURRENT,
        }
    }
}

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_u16(key: &str, default: u16) -> u16 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_string(key: &str, default: &str) -> String {
    std::env::var(key)
        .map(|v| v.trim().to_string())
        .unwrap_or_else(|_| default.to_string())
}

fn env_u64(key: &str, default: u64) -> u64 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.trim().parse().ok())
        .unwrap_or(default)
}

impl Config {
    pub fn from_env() -> Self {
        let d = Self::default();
        Self {
            worker_threads: env_usize("WORKER_THREADS", d.worker_threads),
            max_blocking_threads: env_usize("MAX_BLOCKING_THREADS", d.max_blocking_threads),
            concurrency_limit: env_usize("CONCURRENCY_LIMIT", d.concurrency_limit),
            port: env_u16("PORT", d.port),
            turso_url: env_string("TURSO_DB_URL", ""),
            turso_token: env_string("TURSO_DB_TOKEN", ""),
            replica_path: env_string("REPLICA_PATH", &d.replica_path),
            sync_secs: env_u64("SYNC_SECS", d.sync_secs),
            db_max_concurrent: env_usize("DB_MAX_CONCURRENT", d.db_max_concurrent),
        }
    }

    pub fn normalized_url(&self) -> String {
        let u = self.turso_url.trim().to_string();
        if u.starts_with("turso://") {
            u.replacen("turso://", "libsql://", 1)
        } else {
            u
        }
    }

    pub fn has_db(&self) -> bool {
        !self.normalized_url().is_empty() && !self.turso_token.is_empty()
    }
}
