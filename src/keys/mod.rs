//! API keys — operational state, not published content.
//!
//! Separate from `bank/` because the lifecycles differ: keys are issued,
//! revoked and (later) billed; the bank is immutable published content. The file
//! lives outside `data/` and is gitignored, so credential digests never enter the
//! committed constant (D24/D28).
//!
//! v1 scope: CLI-issued, no accounts, no sessions. `account_id` rides along
//! defaulted to `"local"` so Phase 2 (accounts/dashboard) is additive.

mod store;

pub use store::KeyStore;

use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

fn default_account() -> String {
    "local".to_owned()
}

fn default_plan() -> String {
    "free".to_owned()
}

fn default_scopes() -> String {
    "questions:read reports:write".to_owned()
}

/// A key as stored. Deliberately carries no secret material — no plaintext,
/// no hash. `key_prefix` (first 8 chars of `sk_…`) is for support lookup only
/// and never authenticates.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct ApiKey {
    pub id: String,
    pub label: String,
    #[serde(default = "default_account")]
    pub account_id: String,
    #[serde(default = "default_plan")]
    pub plan: String,
    #[serde(default = "default_scopes")]
    pub scopes: String,
    /// Per-key request allowance (D26) — a column, not a key *type*.
    pub rate_limit: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub quota_monthly: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub key_prefix: Option<String>,
    pub created_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_used_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub suspended_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub suspend_reason: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub revoked_at: Option<String>,
}

/// Lifecycle state, derived — never stored. `Suspended` is reserved for
/// Phase 2 (abuse/billing); v1 ships Active/Revoked/Expired only.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeyStatus {
    Active,
    Suspended,
    Revoked,
    Expired,
}

impl KeyStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Suspended => "suspended",
            Self::Revoked => "revoked",
            Self::Expired => "expired",
        }
    }
}

impl ApiKey {
    pub fn status(&self) -> KeyStatus {
        if self.revoked_at.is_some() {
            return KeyStatus::Revoked;
        }
        if self.suspended_at.is_some() {
            return KeyStatus::Suspended;
        }
        if let Some(exp) = self.expires_at.as_deref() {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0);
            if exp.parse::<u64>().is_ok_and(|e| e <= now) {
                return KeyStatus::Expired;
            }
        }
        KeyStatus::Active
    }

    pub fn is_live(&self) -> bool {
        self.status() == KeyStatus::Active
    }
}
