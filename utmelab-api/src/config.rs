//! Runtime knobs. Defaults are tuned for a small box; every value is
//! overridable by env (tune here). Invalid values fail at boot, never silently.

pub const DEFAULT_WORKER_THREADS: usize = 4;
pub const DEFAULT_MAX_BLOCKING_THREADS: usize = 32;
pub const DEFAULT_CONCURRENCY_LIMIT: usize = 1000;
pub const DEFAULT_PORT: u16 = 3100;
pub const DEFAULT_SERVER_URL: &str = "http://localhost:3100";
pub const DEFAULT_REPLICA_PATH: &str = "db/sync.db";
/// Long-poll window, not a timer. Each pull hangs server-side until a change
/// lands or this elapses. Idle stays idle; changes apply within ~seconds.
pub const DEFAULT_SYNC_SECS: u64 = 60;
pub const DEFAULT_DB_MAX_CONCURRENT: usize = 16;
pub const DEFAULT_READ_TIMEOUT_SECS: u64 = 5;
pub const DEFAULT_WRITE_TIMEOUT_SECS: u64 = 30;

#[derive(Clone)]
pub struct Config {
    pub worker_threads: usize,
    pub max_blocking_threads: usize,
    pub concurrency_limit: usize,
    pub port: u16,
    pub server_url: String,
    pub turso_url: String,
    pub turso_token: String,
    pub replica_path: String,
    pub sync_secs: u64,
    pub db_max_concurrent: usize,
    pub cookie_secure: bool,
    pub read_timeout_secs: u64,
    pub write_timeout_secs: u64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            worker_threads: DEFAULT_WORKER_THREADS,
            max_blocking_threads: DEFAULT_MAX_BLOCKING_THREADS,
            concurrency_limit: DEFAULT_CONCURRENCY_LIMIT,
            port: DEFAULT_PORT,
            server_url: DEFAULT_SERVER_URL.to_string(),
            turso_url: String::new(),
            turso_token: String::new(),
            replica_path: DEFAULT_REPLICA_PATH.to_string(),
            sync_secs: DEFAULT_SYNC_SECS,
            db_max_concurrent: DEFAULT_DB_MAX_CONCURRENT,
            cookie_secure: false,
            read_timeout_secs: DEFAULT_READ_TIMEOUT_SECS,
            write_timeout_secs: DEFAULT_WRITE_TIMEOUT_SECS,
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
            server_url: env_string("SERVER_URL", &d.server_url),
            turso_url: env_string("TURSO_DB_URL", ""),
            turso_token: env_string("TURSO_DB_TOKEN", ""),
            replica_path: env_string("REPLICA_PATH", &d.replica_path),
            sync_secs: env_u64("SYNC_SECS", d.sync_secs),
            db_max_concurrent: env_usize("DB_MAX_CONCURRENT", d.db_max_concurrent),
            cookie_secure: env_string("COOKIE_SECURE", "0") == "1",
            read_timeout_secs: env_u64("READ_TIMEOUT_SECS", d.read_timeout_secs),
            write_timeout_secs: env_u64("WRITE_TIMEOUT_SECS", d.write_timeout_secs),
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

    /// Reads answer from the local replica in milliseconds; anything past
    /// this is a bug, not slowness worth waiting for.
    pub fn fast_timeout(&self) -> tower_http::timeout::TimeoutLayer {
        tower_http::timeout::TimeoutLayer::with_status_code(
            axum::http::StatusCode::REQUEST_TIMEOUT,
            std::time::Duration::from_secs(self.read_timeout_secs),
        )
    }

    /// Writes push to cloud (~seconds from most regions); a slower budget
    /// keeps them usable without letting reads hide behind it.
    pub fn slow_timeout(&self) -> tower_http::timeout::TimeoutLayer {
        tower_http::timeout::TimeoutLayer::with_status_code(
            axum::http::StatusCode::REQUEST_TIMEOUT,
            std::time::Duration::from_secs(self.write_timeout_secs),
        )
    }

    /// Fail fast on nonsense before serving. Called once at boot; a bad
    /// value exits the process with a message instead of a dead server.
    pub fn validate(&self) -> Result<(), String> {
        let bad = |k: &str| format!("invalid config: {k} must be > 0");
        if self.worker_threads == 0 {
            return Err(bad("WORKER_THREADS"));
        }
        if self.max_blocking_threads == 0 {
            return Err(bad("MAX_BLOCKING_THREADS"));
        }
        if self.concurrency_limit == 0 {
            return Err(bad("CONCURRENCY_LIMIT"));
        }
        if self.port == 0 {
            return Err(bad("PORT"));
        }
        if self.sync_secs == 0 {
            return Err(bad("SYNC_SECS"));
        }
        if self.db_max_concurrent == 0 {
            return Err(bad("DB_MAX_CONCURRENT"));
        }
        if self.read_timeout_secs == 0 {
            return Err(bad("READ_TIMEOUT_SECS"));
        }
        if self.write_timeout_secs == 0 {
            return Err(bad("WRITE_TIMEOUT_SECS"));
        }
        Ok(())
    }
}
