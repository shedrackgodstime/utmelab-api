//! Per-key rate limiting (D27).
//!
//! A token bucket per key: `rate_limit` tokens, refilled continuously, capped at
//! `rate_limit`. Chosen over a sliding window because a window stores every
//! request timestamp and a busy key grows without bound; a bucket is O(1) per key
//! regardless of traffic.
//!
//! Enforced inside the [`Caller`](super::auth::Caller) extractor rather than as
//! middleware, so **every authenticated route is limited by construction** — a
//! new handler that takes `Caller` cannot forget to be protected.

use std::collections::HashMap;
use std::time::Instant;

const MINUTE: f64 = 60.0;

#[derive(Debug, Clone, Copy)]
struct Bucket {
    tokens: f64,
    last: Instant,
}

/// Keyed by key id, so two keys never share a budget.
#[derive(Debug, Default)]
pub struct RateLimiter {
    buckets: HashMap<String, Bucket>,
}

impl RateLimiter {
    pub fn new() -> Self {
        Self::default()
    }

    /// Consume one token for `key_id`. `false` means the caller is over budget.
    pub fn check(&mut self, key_id: &str, rate_limit: u32) -> bool {
        self.check_at(key_id, rate_limit, Instant::now())
    }

    /// The clock is a parameter so tests can advance time without sleeping.
    fn check_at(&mut self, key_id: &str, rate_limit: u32, now: Instant) -> bool {
        if rate_limit == 0 {
            return false;
        }
        let capacity = f64::from(rate_limit);

        let bucket = self.buckets.entry(key_id.to_owned()).or_insert(Bucket {
            tokens: capacity,
            last: now,
        });

        // Refill for the time that has passed, never above capacity.
        let elapsed = now.saturating_duration_since(bucket.last).as_secs_f64();
        bucket.tokens = (bucket.tokens + elapsed * capacity / MINUTE).min(capacity);
        bucket.last = now;

        if bucket.tokens >= 1.0 {
            bucket.tokens -= 1.0;
            true
        } else {
            false
        }
    }

    /// Drop buckets for keys that are no longer live, so a long-running process
    /// does not accumulate one entry per key ever issued.
    pub fn retain(&mut self, live: impl Fn(&str) -> bool) {
        self.buckets.retain(|id, _| live(id));
    }

    /// What the caller may be told about its budget, without spending a token.
    /// Returns `(limit, remaining, reset_secs)`: remaining is whole requests
    /// still available, reset is seconds until at least one more is.
    ///
    /// Read-only: an unknown key is reported at full budget (nothing spent),
    /// and `rate_limit == 0` (always-denied) reports a 60s wait rather than
    /// dividing by a zero refill rate.
    pub fn peek(&self, key_id: &str, rate_limit: u32) -> (u32, u32, u64) {
        if rate_limit == 0 {
            return (0, 0, 60);
        }
        let capacity = f64::from(rate_limit);
        match self.buckets.get(key_id) {
            Some(bucket) => {
                let elapsed = Instant::now()
                    .saturating_duration_since(bucket.last)
                    .as_secs_f64();
                let tokens = (bucket.tokens + elapsed * capacity / MINUTE).min(capacity);
                let per_second = capacity / MINUTE;
                let reset = if tokens >= 1.0 {
                    0
                } else {
                    ((1.0 - tokens) / per_second).ceil() as u64
                };
                (rate_limit, tokens.floor() as u32, reset)
            }
            None => (rate_limit, rate_limit, 0),
        }
    }

    #[cfg(test)]
    pub fn buckets(&self) -> usize {
        self.buckets.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A fixed origin for every test so they are deterministic.
    fn at(secs: u64) -> Instant {
        Instant::now() + std::time::Duration::from_secs(secs)
    }

    #[test]
    fn a_key_gets_its_full_budget_then_is_refused() {
        let mut l = RateLimiter::new();
        for i in 0..10 {
            assert!(l.check_at("k1", 10, at(0)), "request {i} should pass");
        }
        assert!(!l.check_at("k1", 10, at(0)), "the 11th is over budget");
    }

    #[test]
    fn budgets_are_per_key() {
        let mut l = RateLimiter::new();
        assert!(l.check_at("k1", 1, at(0)));
        assert!(!l.check_at("k1", 1, at(0)));
        // A different key is unaffected by the first one's exhaustion.
        assert!(l.check_at("k2", 1, at(0)));
    }

    #[test]
    fn budget_refills_over_time_but_never_past_the_cap() {
        let mut l = RateLimiter::new();
        assert!(l.check_at("k1", 10, at(0)));
        assert!(l.check_at("k1", 10, at(0)));

        // A minute later it is completely replenished.
        let later = at(60);
        for _ in 0..10 {
            assert!(l.check_at("k1", 10, later), "should have refilled");
        }
        assert!(!l.check_at("k1", 10, later), "but never above the cap");

        // Half a minute refills half the budget.
        let mut l2 = RateLimiter::new();
        for _ in 0..10 {
            l2.check_at("k2", 10, at(0));
        }
        let half = at(30);
        let mut allowed = 0;
        for _ in 0..12 {
            if l2.check_at("k2", 10, half) {
                allowed += 1;
            }
        }
        assert!((4..=6).contains(&allowed), "expected ~5, got {allowed}");
    }

    #[test]
    fn a_zero_limit_admits_nothing() {
        let mut l = RateLimiter::new();
        assert!(!l.check_at("k1", 0, at(0)));
    }

    #[test]
    fn peek_reports_the_budget_without_spending_it() {
        let mut l = RateLimiter::new();
        // Unknown key: full budget, nothing spent.
        assert_eq!(l.peek("k1", 10), (10, 10, 0));

        // Spend 3 of 10.
        for _ in 0..3 {
            l.check_at("k1", 10, at(0));
        }
        assert_eq!(l.peek("k1", 10), (10, 7, 0));

        // Spend the rest: remaining 0, reset counts up to a refill.
        for _ in 0..7 {
            l.check_at("k1", 10, at(0));
        }
        let (limit, remaining, reset) = l.peek("k1", 10);
        assert_eq!(limit, 10);
        assert_eq!(remaining, 0);
        assert!(
            (1..=60).contains(&reset),
            "one token is never 60s+ away: {reset}"
        );

        // Peek must not spend: still 0 remaining, still refused.
        assert!(!l.check_at("k1", 10, at(0)));
        assert_eq!(l.peek("k1", 10).1, 0);
    }

    #[test]
    fn peek_survives_a_zero_limit() {
        let l = RateLimiter::new();
        assert_eq!(l.peek("k0", 0), (0, 0, 60), "no divide-by-zero on refill");
    }

    #[test]
    fn dead_keys_are_evicted() {
        let mut l = RateLimiter::new();
        l.check_at("live", 10, at(0));
        l.check_at("dead", 10, at(0));
        assert_eq!(l.buckets(), 2);
        l.retain(|id| id == "live");
        assert_eq!(l.buckets(), 1);
    }
}
