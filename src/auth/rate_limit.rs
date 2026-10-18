//! One sliding-window limiter shared by every surface. Callers pick a
//! bucket key (`login:<ip>`, later `key:<prefix>`); parameters live here
//! so limits change in exactly one place.

use std::{
    collections::{HashMap, VecDeque},
    time::{Duration, Instant},
};

use tokio::sync::Mutex;

use crate::config::{DEFAULT_RATE_LIMIT_ADMIN_PER_MIN, DEFAULT_RATE_LIMIT_PER_MIN};

pub const LOGIN_MAX_PER_MINUTE: u32 = 10;
pub const LOGIN_WINDOW: Duration = Duration::from_secs(60);
/// Public-surface window. Fixed at a minute so the `Retry-After: 60` we
/// answer a throttle with is always truthful.
pub const API_WINDOW: Duration = Duration::from_secs(60);
/// Discovery-surface ceiling, per caller IP. A funnel page costs one or two
/// requests, so this is generous for a shared school NAT and still bounds a
/// script. The catalog is public by design, so this is abuse protection, not
/// secrecy: it cannot be the thing that keeps the taxonomy in.
pub const PUBLIC_MAX_PER_MINUTE: u32 = 120;
const MAX_BUCKETS: usize = 10_000;

pub struct RateLimiter {
    inner: Mutex<HashMap<String, VecDeque<Instant>>>,
    api_per_min: u32,
    api_admin_per_min: u32,
}

impl Default for RateLimiter {
    fn default() -> Self {
        Self::with_api_limits(DEFAULT_RATE_LIMIT_PER_MIN, DEFAULT_RATE_LIMIT_ADMIN_PER_MIN)
    }
}

impl RateLimiter {
    pub fn new() -> Self {
        Self::default()
    }

    /// Build with the public-surface policy from config.
    pub fn with_api_limits(api_per_min: u32, api_admin_per_min: u32) -> Self {
        Self {
            inner: Mutex::new(HashMap::new()),
            api_per_min,
            api_admin_per_min,
        }
    }

    /// True when the call is allowed (and recorded). False means throttled.
    pub async fn check(&self, key: &str, max: u32, window: Duration) -> bool {
        let mut map = self.inner.lock().await;
        let now = Instant::now();
        let q = map.entry(key.to_string()).or_default();
        while q.front().is_some_and(|t| now.duration_since(*t) > window) {
            q.pop_front();
        }
        if q.len() as u32 >= max {
            return false;
        }
        q.push_back(now);
        if map.len() > MAX_BUCKETS {
            map.retain(|_, v| v.back().is_some_and(|t| now.duration_since(*t) <= window));
        }
        true
    }

    pub async fn check_login(&self, ip: &str) -> bool {
        self.check(&format!("login:{ip}"), LOGIN_MAX_PER_MINUTE, LOGIN_WINDOW)
            .await
    }

    /// Public-surface ceiling, keyed by the verified key id. Called from the
    /// key extractor, so `api` and `mcp` share it and no route can forget.
    /// A zero limit, or an admin key, means unlimited.
    pub async fn check_api_key(&self, key_id: &str, is_admin: bool) -> bool {
        let limit = if is_admin {
            self.api_admin_per_min
        } else {
            self.api_per_min
        };
        if limit == 0 {
            return true;
        }
        self.check(&format!("key:{key_id}"), limit, API_WINDOW)
            .await
    }

    /// Discovery-surface ceiling, keyed by caller IP because there is no key
    /// to key on. Called from `middleware::public_limit`, which is why the
    /// keyless routes cannot ship unmetered.
    pub async fn check_public(&self, ip: &str) -> bool {
        self.check(&format!("public:{ip}"), PUBLIC_MAX_PER_MINUTE, API_WINDOW)
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn burst_over_limit_throttles() {
        let r = RateLimiter::new();
        for _ in 0..10 {
            assert!(r.check_login("1.1.1.1").await);
        }
        assert!(!r.check_login("1.1.1.1").await);
        assert!(r.check_login("2.2.2.2").await);
    }

    #[tokio::test]
    async fn window_expiry_readmits() {
        let r = RateLimiter::new();
        assert!(r.check("k", 1, Duration::from_millis(40)).await);
        assert!(!r.check("k", 1, Duration::from_millis(40)).await);
        tokio::time::sleep(Duration::from_millis(60)).await;
        assert!(r.check("k", 1, Duration::from_millis(40)).await);
    }

    #[tokio::test]
    async fn api_key_limit_is_per_key_and_admin_is_unlimited() {
        let r = RateLimiter::with_api_limits(2, 0);
        assert!(r.check_api_key("key-a", false).await);
        assert!(r.check_api_key("key-a", false).await);
        assert!(!r.check_api_key("key-a", false).await);
        assert!(
            r.check_api_key("key-b", false).await,
            "a different key is unaffected"
        );
        for _ in 0..50 {
            assert!(r.check_api_key("ops", true).await, "admin bypasses");
        }
    }

    #[tokio::test]
    async fn zero_limit_disables_api_throttling() {
        let r = RateLimiter::with_api_limits(0, 0);
        for _ in 0..200 {
            assert!(r.check_api_key("key-a", false).await);
        }
    }
}
