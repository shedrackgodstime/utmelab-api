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
/// Seconds between background replica pulls, and therefore the bound on how
/// long a change made elsewhere can take to land on this replica. Reads never
/// queue behind the sync (they run on pooled connections); a write waits for a
/// pull in progress, because both hold the same mutex, and never for more than
/// one pull. Not a long-poll window: each tick waits, pulls once, and leaves
/// the worker free in between.
///
/// Measured against the real remote, not inherited: an empty pull is one round
/// trip, ~0.2s while the HTTP connection is still warm and ~0.7s once it has
/// sat idle and been re-established, carrying ~160 bytes of sync payload and
/// ~2.3KB of local log writes. Idle at this window measured 0.05% of one core,
/// no held request, no busy loop. So a window of N seconds spends about one
/// pull's time in N of the serialized write path and costs the remote one
/// request per window: 10s is ~6 requests/minute and holds a write behind a
/// pull for at most ~0.7s. Windows at or below ~5s pay the connection setup on
/// every tick for a freshness gain nobody can perceive; raise it to trade
/// propagation delay for less chatter.
pub const DEFAULT_SYNC_SECS: u64 = 10;
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
/// Base URL where figure images and media assets are served.
pub const DEFAULT_MEDIA_BASE_URL: &str = "https://assets.utmelab.com/images";

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
            sync_secs: DEFAULT_SYNC_SECS,
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
            sync_secs: number(source, "SYNC_SECS", d.sync_secs)?,
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
        assert!(parse(&[("SYNC_SECS", "-1")]).is_err());
        assert!(parse(&[("DB_MAX_CONCURRENT", "many")]).is_err());
    }

    #[test]
    fn zero_parses_but_fails_validation() {
        assert!(parse(&[("PORT", "0")]).is_err());
        assert!(parse(&[("WORKER_THREADS", "0")]).is_err());
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
