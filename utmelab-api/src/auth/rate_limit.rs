//! One sliding-window limiter shared by every surface. Callers pick a
//! bucket key (`login:<ip>`, later `key:<prefix>`); parameters live here
//! so limits change in exactly one place.

use std::{
    collections::{HashMap, VecDeque},
    time::{Duration, Instant},
};

use tokio::sync::Mutex;

pub const LOGIN_MAX_PER_MINUTE: u32 = 10;
pub const LOGIN_WINDOW: Duration = Duration::from_secs(60);
const MAX_BUCKETS: usize = 10_000;

#[derive(Default)]
pub struct RateLimiter {
    inner: Mutex<HashMap<String, VecDeque<Instant>>>,
}

impl RateLimiter {
    pub fn new() -> Self {
        Self::default()
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
}
