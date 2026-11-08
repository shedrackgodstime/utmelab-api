//! Runtime knobs. Defaults are tuned for a small box; every value is
//! overridable by env (tune here). Parsing is strict: a variable that is set
//! must be valid or boot fails naming it, and a blank value counts as unset so
//! an empty override never masquerades as a real one.

pub const DEFAULT_WORKER_THREADS: usize = 4;
pub const DEFAULT_MAX_BLOCKING_THREADS: usize = 32;
pub const DEFAULT_CONCURRENCY_LIMIT: usize = 1000;
pub const DEFAULT_PORT: u16 = 3100;
/// Host the listener binds. Loopback-only on purpose, and load-bearing: the
/// rate limiter trusts the address the reverse proxy attests, which is only
/// sound while nothing can reach the binary without going through that proxy.
/// Exposing this port directly means revisiting
/// [`crate::auth::session::client_ip`] first, so it is a constant, not a knob.
pub const BIND_HOST: [u8; 4] = [127, 0, 0, 1];
pub const DEFAULT_SERVER_URL: &str = "http://localhost:3100";
pub const DEFAULT_REPLICA_PATH: &str = "db/sync.db";
/// After this many seconds without real traffic, the long-poll pull loop
/// sleeps. The first database request wakes it with one locked pull.
pub const DEFAULT_SYNC_IDLE_SECS: u64 = 300;
/// Turso caps effective long-polling at five seconds. Three seconds leaves
/// room below the default five-second read timeout for the first request that
/// wakes a sleeping replica.
pub const DEFAULT_SYNC_LONG_POLL_SECS: u64 = 3;

#[derive(Clone, Copy)]
pub enum SyncMode {
    LongPoll { idle_after_secs: u64 },
}

impl SyncMode {
    pub const fn default() -> Self {
        Self::LongPoll {
            idle_after_secs: DEFAULT_SYNC_IDLE_SECS,
        }
    }

    pub const fn idle_after_secs(self) -> u64 {
        match self {
            Self::LongPoll { idle_after_secs } => idle_after_secs,
        }
    }
}
/// Sync operation budgets. Every engine call has one; a call without a
/// budget is a bug, not a default. The long poll runs inside the pull budget,
/// so the pull budget must exceed `SYNC_LONG_POLL_SECS`.
pub const DEFAULT_SYNC_BUILD_TIMEOUT_SECS: u64 = 60;
pub const DEFAULT_SYNC_CONNECT_TIMEOUT_SECS: u64 = 5;
pub const DEFAULT_SYNC_PULL_TIMEOUT_SECS: u64 = 30;
pub const DEFAULT_SYNC_PUSH_TIMEOUT_SECS: u64 = 30;
pub const DEFAULT_SYNC_STATS_TIMEOUT_SECS: u64 = 5;
pub const DEFAULT_SYNC_VERIFY_TIMEOUT_SECS: u64 = 15;
pub const DEFAULT_SYNC_SHUTDOWN_TIMEOUT_SECS: u64 = 15;
/// Retry cadence for sync work: base, doubling factor, ceiling, additive
/// jitter percentage, and the slow probe used for permanent errors.
pub const DEFAULT_SYNC_RETRY_BASE_SECS: u64 = 5;
pub const DEFAULT_SYNC_RETRY_MAX_SECS: u64 = 60;
pub const DEFAULT_SYNC_RETRY_FACTOR: u32 = 2;
pub const DEFAULT_SYNC_RETRY_JITTER_PCT: u8 = 20;
pub const DEFAULT_SYNC_PERMANENT_PROBE_SECS: u64 = 300;
/// How long the last successful pull may back content and credentials.
/// Content can be older than credentials: a stale catalog is inconvenient,
/// a stale revocation list is a security boundary.
pub const DEFAULT_SYNC_MAX_STALENESS_SECS: u64 = 900;
pub const DEFAULT_SYNC_AUTH_MAX_STALENESS_SECS: u64 = 300;
/// The supervisor stamps a heartbeat every loop. A gap past this budget means
/// the task is no longer running and readiness must stop trusting the replica.
pub const DEFAULT_SYNC_HEARTBEAT_MAX_SECS: u64 = 180;
/// Local work committed during a push outage is bounded. New writes are
/// refused once the process-local pending counter reaches either limit.
pub const DEFAULT_SYNC_MAX_PENDING_OPERATIONS: u64 = 256;
pub const DEFAULT_SYNC_MAX_PENDING_BYTES: u64 = 64 * 1024 * 1024;
pub const DEFAULT_DB_MAX_CONCURRENT: usize = 16;
/// Secure-by-default: a session cookie is only non-`Secure` when an operator
/// explicitly sets `COOKIE_SECURE=0` for local http work. A typo or a missing
/// variable must fail closed, never downgrade the cookie silently.
pub const DEFAULT_COOKIE_SECURE: bool = true;
pub const DEFAULT_READ_TIMEOUT_SECS: u64 = 5;
pub const DEFAULT_WRITE_TIMEOUT_SECS: u64 = 30;
/// Per-key request ceiling per minute on the public surfaces (`api` and
/// `mcp`). 0 disables per-key limiting. Admin keys use the admin knob.
/// 60 is the figure the public docs promise customers ("60 requests a minute
/// per key"), so the default is that promise, not a value free to drift from
/// the docs. The old service defaulted to 60 too.
pub const DEFAULT_RATE_LIMIT_PER_MIN: u32 = 60;
/// Admin keys are internal (monitoring, provisioning), so unlimited by
/// default. Set a positive value to bound them too.
pub const DEFAULT_RATE_LIMIT_ADMIN_PER_MIN: u32 = 0;
/// Base URL where media assets are served. Image references add `/images/`
/// when they are resolved; other asset families can use this same host.
pub const DEFAULT_MEDIA_BASE_URL: &str =
    "https://gitlab.com/shedrackgodstime/utmelab-bank/-/raw/main/";

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
    pub sync_mode: SyncMode,
    pub sync_long_poll_secs: u64,
    pub sync_build_timeout_secs: u64,
    pub sync_connect_timeout_secs: u64,
    pub sync_pull_timeout_secs: u64,
    pub sync_push_timeout_secs: u64,
    pub sync_stats_timeout_secs: u64,
    pub sync_verify_timeout_secs: u64,
    pub sync_shutdown_timeout_secs: u64,
    pub sync_retry_base_secs: u64,
    pub sync_retry_max_secs: u64,
    pub sync_retry_factor: u32,
    pub sync_retry_jitter_pct: u8,
    pub sync_permanent_probe_secs: u64,
    pub sync_max_staleness_secs: u64,
    pub sync_auth_max_staleness_secs: u64,
    pub sync_heartbeat_max_secs: u64,
    pub sync_max_pending_operations: u64,
    pub sync_max_pending_bytes: u64,
    pub db_max_concurrent: usize,
    pub cookie_secure: bool,
    pub read_timeout_secs: u64,
    pub write_timeout_secs: u64,
    pub rate_limit_per_min: u32,
    pub rate_limit_admin_per_min: u32,
    pub media_base_url: String,
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
            sync_mode: SyncMode::default(),
            sync_long_poll_secs: DEFAULT_SYNC_LONG_POLL_SECS,
            sync_build_timeout_secs: DEFAULT_SYNC_BUILD_TIMEOUT_SECS,
            sync_connect_timeout_secs: DEFAULT_SYNC_CONNECT_TIMEOUT_SECS,
            sync_pull_timeout_secs: DEFAULT_SYNC_PULL_TIMEOUT_SECS,
            sync_push_timeout_secs: DEFAULT_SYNC_PUSH_TIMEOUT_SECS,
            sync_stats_timeout_secs: DEFAULT_SYNC_STATS_TIMEOUT_SECS,
            sync_verify_timeout_secs: DEFAULT_SYNC_VERIFY_TIMEOUT_SECS,
            sync_shutdown_timeout_secs: DEFAULT_SYNC_SHUTDOWN_TIMEOUT_SECS,
            sync_retry_base_secs: DEFAULT_SYNC_RETRY_BASE_SECS,
            sync_retry_max_secs: DEFAULT_SYNC_RETRY_MAX_SECS,
            sync_retry_factor: DEFAULT_SYNC_RETRY_FACTOR,
            sync_retry_jitter_pct: DEFAULT_SYNC_RETRY_JITTER_PCT,
            sync_permanent_probe_secs: DEFAULT_SYNC_PERMANENT_PROBE_SECS,
            sync_max_staleness_secs: DEFAULT_SYNC_MAX_STALENESS_SECS,
            sync_auth_max_staleness_secs: DEFAULT_SYNC_AUTH_MAX_STALENESS_SECS,
            sync_heartbeat_max_secs: DEFAULT_SYNC_HEARTBEAT_MAX_SECS,
            sync_max_pending_operations: DEFAULT_SYNC_MAX_PENDING_OPERATIONS,
            sync_max_pending_bytes: DEFAULT_SYNC_MAX_PENDING_BYTES,
            db_max_concurrent: DEFAULT_DB_MAX_CONCURRENT,
            cookie_secure: DEFAULT_COOKIE_SECURE,
            read_timeout_secs: DEFAULT_READ_TIMEOUT_SECS,
            write_timeout_secs: DEFAULT_WRITE_TIMEOUT_SECS,
            rate_limit_per_min: DEFAULT_RATE_LIMIT_PER_MIN,
            rate_limit_admin_per_min: DEFAULT_RATE_LIMIT_ADMIN_PER_MIN,
            media_base_url: DEFAULT_MEDIA_BASE_URL.to_string(),
        }
    }
}

/// A lookup that yields a raw value for a key, as the environment would.
/// Injected so parsing is testable without mutating process-global state.
type Source<'a> = &'a dyn Fn(&str) -> Option<String>;

/// Trimmed value, or `None` when unset or blank. Blank is unset: an empty
/// override is a mistake, not a request for an empty string.
fn raw(source: Source, key: &str) -> Option<String> {
    source(key)
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

fn text(source: Source, key: &str, default: &str) -> String {
    raw(source, key).unwrap_or_else(|| default.to_string())
}

/// Parse a set value, or fall back to the default when unset. A value that
/// is present but unparseable is an error that names the variable.
fn number<T: std::str::FromStr>(source: Source, key: &str, default: T) -> Result<T, String> {
    match raw(source, key) {
        None => Ok(default),
        Some(v) => v
            .parse::<T>()
            .map_err(|_| format!("invalid config: {key}={v:?} is not a valid number")),
    }
}

/// Booleans are spelled, not guessed: an unrecognized truthiness is an error
/// rather than a silent `false`. That matters most for `COOKIE_SECURE`, where
/// a typo would otherwise quietly downgrade a security setting.
fn boolean(source: Source, key: &str, default: bool) -> Result<bool, String> {
    match raw(source, key) {
        None => Ok(default),
        Some(v) => match v.to_ascii_lowercase().as_str() {
            "1" | "true" | "yes" | "on" => Ok(true),
            "0" | "false" | "no" | "off" => Ok(false),
            _ => Err(format!(
                "invalid config: {key}={v:?} is not a boolean (use 1/0 or true/false)"
            )),
        },
    }
}

impl Config {
    /// Parse and validate every knob. Returns the offending variable on a
    /// bad value instead of quietly serving with a default.
    pub fn from_env() -> Result<Self, String> {
        Self::from_source(&|k| std::env::var(k).ok())
    }

    /// Testable core of [`Config::from_env`].
    fn from_source(source: Source) -> Result<Self, String> {
        let d = Self::default();
        let cfg = Self {
            worker_threads: number(source, "WORKER_THREADS", d.worker_threads)?,
            max_blocking_threads: number(source, "MAX_BLOCKING_THREADS", d.max_blocking_threads)?,
            concurrency_limit: number(source, "CONCURRENCY_LIMIT", d.concurrency_limit)?,
            port: number(source, "PORT", d.port)?,
            server_url: text(source, "SERVER_URL", &d.server_url),
            turso_url: text(source, "TURSO_DB_URL", ""),
            turso_token: text(source, "TURSO_DB_TOKEN", ""),
            replica_path: text(source, "REPLICA_PATH", &d.replica_path),
            sync_mode: SyncMode::LongPoll {
                idle_after_secs: number(source, "SYNC_IDLE_SECS", d.sync_mode.idle_after_secs())?,
            },
            sync_long_poll_secs: number(source, "SYNC_LONG_POLL_SECS", d.sync_long_poll_secs)?,
            sync_build_timeout_secs: number(
                source,
                "SYNC_BUILD_TIMEOUT_SECS",
                d.sync_build_timeout_secs,
            )?,
            sync_connect_timeout_secs: number(
                source,
                "SYNC_CONNECT_TIMEOUT_SECS",
                d.sync_connect_timeout_secs,
            )?,
            sync_pull_timeout_secs: number(
                source,
                "SYNC_PULL_TIMEOUT_SECS",
                d.sync_pull_timeout_secs,
            )?,
            sync_push_timeout_secs: number(
                source,
                "SYNC_PUSH_TIMEOUT_SECS",
                d.sync_push_timeout_secs,
            )?,
            sync_stats_timeout_secs: number(
                source,
                "SYNC_STATS_TIMEOUT_SECS",
                d.sync_stats_timeout_secs,
            )?,
            sync_verify_timeout_secs: number(
                source,
                "SYNC_VERIFY_TIMEOUT_SECS",
                d.sync_verify_timeout_secs,
            )?,
            sync_shutdown_timeout_secs: number(
                source,
                "SYNC_SHUTDOWN_TIMEOUT_SECS",
                d.sync_shutdown_timeout_secs,
            )?,
            sync_retry_base_secs: number(source, "SYNC_RETRY_BASE_SECS", d.sync_retry_base_secs)?,
            sync_retry_max_secs: number(source, "SYNC_RETRY_MAX_SECS", d.sync_retry_max_secs)?,
            sync_retry_factor: number(source, "SYNC_RETRY_FACTOR", d.sync_retry_factor)?,
            sync_retry_jitter_pct: number(
                source,
                "SYNC_RETRY_JITTER_PCT",
                d.sync_retry_jitter_pct,
            )?,
            sync_permanent_probe_secs: number(
                source,
                "SYNC_PERMANENT_PROBE_SECS",
                d.sync_permanent_probe_secs,
            )?,
            sync_max_staleness_secs: number(
                source,
                "SYNC_MAX_STALENESS_SECS",
                d.sync_max_staleness_secs,
            )?,
            sync_auth_max_staleness_secs: number(
                source,
                "SYNC_AUTH_MAX_STALENESS_SECS",
                d.sync_auth_max_staleness_secs,
            )?,
            sync_heartbeat_max_secs: number(
                source,
                "SYNC_HEARTBEAT_MAX_SECS",
                d.sync_heartbeat_max_secs,
            )?,
            sync_max_pending_operations: number(
                source,
                "SYNC_MAX_PENDING_OPERATIONS",
                d.sync_max_pending_operations,
            )?,
            sync_max_pending_bytes: number(
                source,
                "SYNC_MAX_PENDING_BYTES",
                d.sync_max_pending_bytes,
            )?,
            db_max_concurrent: number(source, "DB_MAX_CONCURRENT", d.db_max_concurrent)?,
            cookie_secure: boolean(source, "COOKIE_SECURE", d.cookie_secure)?,
            read_timeout_secs: number(source, "READ_TIMEOUT_SECS", d.read_timeout_secs)?,
            write_timeout_secs: number(source, "WRITE_TIMEOUT_SECS", d.write_timeout_secs)?,
            rate_limit_per_min: number(source, "RATE_LIMIT_PER_MIN", d.rate_limit_per_min)?,
            rate_limit_admin_per_min: number(
                source,
                "RATE_LIMIT_ADMIN_PER_MIN",
                d.rate_limit_admin_per_min,
            )?,
            media_base_url: raw(source, "MEDIA_BASE_URL")
                .or_else(|| raw(source, "UTMELAB_MEDIA_BASE_URL"))
                .unwrap_or_else(|| d.media_base_url.clone()),
        };
        cfg.validate()?;
        Ok(cfg)
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
        if self.sync_mode.idle_after_secs() == 0 {
            return Err(bad("SYNC_IDLE_SECS"));
        }
        if self.sync_long_poll_secs == 0 || self.sync_long_poll_secs > 5 {
            return Err("invalid config: SYNC_LONG_POLL_SECS must be 1-5".to_string());
        }
        if self.sync_long_poll_secs >= self.read_timeout_secs {
            return Err(
                "invalid config: SYNC_LONG_POLL_SECS must be less than READ_TIMEOUT_SECS"
                    .to_string(),
            );
        }
        for (key, value) in [
            ("SYNC_BUILD_TIMEOUT_SECS", self.sync_build_timeout_secs),
            ("SYNC_CONNECT_TIMEOUT_SECS", self.sync_connect_timeout_secs),
            ("SYNC_PULL_TIMEOUT_SECS", self.sync_pull_timeout_secs),
            ("SYNC_PUSH_TIMEOUT_SECS", self.sync_push_timeout_secs),
            ("SYNC_STATS_TIMEOUT_SECS", self.sync_stats_timeout_secs),
            ("SYNC_VERIFY_TIMEOUT_SECS", self.sync_verify_timeout_secs),
            (
                "SYNC_SHUTDOWN_TIMEOUT_SECS",
                self.sync_shutdown_timeout_secs,
            ),
            ("SYNC_RETRY_BASE_SECS", self.sync_retry_base_secs),
            ("SYNC_RETRY_MAX_SECS", self.sync_retry_max_secs),
            ("SYNC_PERMANENT_PROBE_SECS", self.sync_permanent_probe_secs),
            ("SYNC_MAX_STALENESS_SECS", self.sync_max_staleness_secs),
            (
                "SYNC_AUTH_MAX_STALENESS_SECS",
                self.sync_auth_max_staleness_secs,
            ),
            ("SYNC_HEARTBEAT_MAX_SECS", self.sync_heartbeat_max_secs),
            (
                "SYNC_MAX_PENDING_OPERATIONS",
                self.sync_max_pending_operations,
            ),
            ("SYNC_MAX_PENDING_BYTES", self.sync_max_pending_bytes),
        ] {
            if value == 0 {
                return Err(bad(key));
            }
        }
        if self.sync_pull_timeout_secs <= self.sync_long_poll_secs {
            return Err(
                "invalid config: SYNC_PULL_TIMEOUT_SECS must be greater than SYNC_LONG_POLL_SECS"
                    .to_string(),
            );
        }
        if self.sync_retry_factor == 0 {
            return Err(bad("SYNC_RETRY_FACTOR"));
        }
        if self.sync_retry_max_secs < self.sync_retry_base_secs {
            return Err(
                "invalid config: SYNC_RETRY_MAX_SECS must be at least SYNC_RETRY_BASE_SECS"
                    .to_string(),
            );
        }
        if self.sync_retry_jitter_pct > 100 {
            return Err("invalid config: SYNC_RETRY_JITTER_PCT must be 0-100".to_string());
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
        if self.media_base_url.trim().is_empty() {
            return Err("invalid config: MEDIA_BASE_URL must not be empty".to_string());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(pairs: &[(&str, &str)]) -> Result<Config, String> {
        let owned: Vec<(String, String)> = pairs
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect();
        Config::from_source(&move |k| {
            owned
                .iter()
                .find(|(key, _)| key == k)
                .map(|(_, v)| v.clone())
        })
    }

    #[test]
    fn unset_variables_take_defaults() {
        let c = parse(&[]).expect("defaults are valid");
        assert_eq!(c.port, DEFAULT_PORT);
        assert_eq!(c.worker_threads, DEFAULT_WORKER_THREADS);
        assert_eq!(c.replica_path, DEFAULT_REPLICA_PATH);
        assert!(c.cookie_secure, "secure must be the default, not opt-in");
    }

    #[test]
    fn blank_counts_as_unset() {
        let c = parse(&[("PORT", "   "), ("REPLICA_PATH", "")]).expect("blank falls back");
        assert_eq!(c.port, DEFAULT_PORT);
        assert_eq!(c.replica_path, DEFAULT_REPLICA_PATH);
    }

    #[test]
    fn malformed_numbers_fail_naming_the_variable() {
        let err = parse(&[("PORT", "abc")]).err().expect("must reject abc");
        assert!(
            err.contains("PORT"),
            "message must name the variable: {err}"
        );
        assert!(parse(&[("SYNC_IDLE_SECS", "-1")]).is_err());
        assert!(parse(&[("DB_MAX_CONCURRENT", "many")]).is_err());
    }

    #[test]
    fn zero_parses_but_fails_validation() {
        assert!(parse(&[("PORT", "0")]).is_err());
        assert!(parse(&[("WORKER_THREADS", "0")]).is_err());
    }

    /// Every sync budget is a boot-time contract. A zero or an impossible
    /// relationship must fail the boot naming the variable, never degrade to
    /// an accidental default or an unbounded wait.
    #[test]
    fn sync_policy_is_complete_and_validated() {
        let c = parse(&[("SYNC_CONNECT_TIMEOUT_SECS", "7")]).expect("valid override");
        assert_eq!(c.sync_connect_timeout_secs, 7);
        assert_eq!(c.sync_build_timeout_secs, DEFAULT_SYNC_BUILD_TIMEOUT_SECS);
        assert_eq!(c.sync_pull_timeout_secs, DEFAULT_SYNC_PULL_TIMEOUT_SECS);
        assert_eq!(c.sync_max_staleness_secs, DEFAULT_SYNC_MAX_STALENESS_SECS);
        assert_eq!(
            c.sync_auth_max_staleness_secs,
            DEFAULT_SYNC_AUTH_MAX_STALENESS_SECS
        );
        assert_eq!(
            c.sync_max_pending_operations,
            DEFAULT_SYNC_MAX_PENDING_OPERATIONS
        );
        assert_eq!(c.sync_max_pending_bytes, DEFAULT_SYNC_MAX_PENDING_BYTES);

        let err = parse(&[("SYNC_PULL_TIMEOUT_SECS", "0")])
            .err()
            .expect("zero pull budget must fail");
        assert!(err.contains("SYNC_PULL_TIMEOUT_SECS"), "{err}");

        let err = parse(&[("SYNC_PULL_TIMEOUT_SECS", "3")])
            .err()
            .expect("pull budget must exceed the long poll");
        assert!(err.contains("SYNC_PULL_TIMEOUT_SECS"), "{err}");

        assert!(parse(&[("SYNC_RETRY_MAX_SECS", "1")]).is_err());
        assert!(parse(&[("SYNC_RETRY_FACTOR", "0")]).is_err());
        assert!(parse(&[("SYNC_RETRY_JITTER_PCT", "101")]).is_err());
        assert!(parse(&[("SYNC_HEARTBEAT_MAX_SECS", "0")]).is_err());
        assert!(parse(&[("SYNC_MAX_PENDING_OPERATIONS", "0")]).is_err());
        assert!(parse(&[("SYNC_MAX_PENDING_BYTES", "0")]).is_err());
    }

    #[test]
    fn booleans_accept_common_spellings_and_reject_junk() {
        assert!(
            parse(&[("COOKIE_SECURE", "true")])
                .expect("true")
                .cookie_secure
        );
        assert!(parse(&[("COOKIE_SECURE", "1")]).expect("1").cookie_secure);
        assert!(parse(&[("COOKIE_SECURE", "ON")]).expect("ON").cookie_secure);
        assert!(
            !parse(&[("COOKIE_SECURE", "off")])
                .expect("off")
                .cookie_secure
        );
        assert!(parse(&[("COOKIE_SECURE", "maybe")]).is_err());
    }

    /// The listener is loopback-only, and that is what makes the address the
    /// proxy attests trustworthy: nobody can reach the binary to claim one
    /// directly. If this fails, the trust order in
    /// [`crate::auth::session::client_ip`] changed with it, so read the
    /// comment on [`BIND_HOST`] before touching this assertion.
    #[test]
    fn the_listener_stays_loopback_so_the_proxy_can_be_trusted() {
        assert_eq!(BIND_HOST, [127, 0, 0, 1]);
    }

    #[test]
    fn media_base_url_defaults_and_overrides() {
        let def = parse(&[]).expect("default config");
        assert_eq!(def.media_base_url, DEFAULT_MEDIA_BASE_URL);

        let custom =
            parse(&[("MEDIA_BASE_URL", "https://cdn.example.com/assets")]).expect("custom config");
        assert_eq!(custom.media_base_url, "https://cdn.example.com/assets");

        let utmelab_prefix = parse(&[("UTMELAB_MEDIA_BASE_URL", "https://cdn2.example.com")])
            .expect("prefix config");
        assert_eq!(utmelab_prefix.media_base_url, "https://cdn2.example.com");
    }
}
