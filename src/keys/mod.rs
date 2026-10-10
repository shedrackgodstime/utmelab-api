//! API keys — operational state, not published content.
//!
//! Separate from `bank/` because the lifecycles differ: keys are issued,
//! revoked and (later) billed; the bank is immutable published content. The file
//! lives outside `data/` and is gitignored, so credential digests never enter the
//! committed constant (D24/D28).

mod store;

pub use store::KeyStore;

use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

/// A key as stored. Deliberately carries no secret material.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct ApiKey {
    pub id: String,
    pub label: String,
    /// Per-key request allowance (D26) — a column, not a key *type*.
    pub rate_limit: u32,
    pub created_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub revoked_at: Option<String>,
}
