//! Ops, admin, and account shapes.
//!
//! These describe the service and the caller's own credentials, never bank
//! content: the wire forms behind the meta, status, and key surfaces.

use serde::Serialize;

#[derive(Serialize, utoipa::ToSchema)]
pub struct TableRef {
    pub name: String,
}

#[derive(Serialize)]
pub struct ServiceStatus {
    pub service: &'static str,
    pub has_sync: bool,
    pub contract_ok: bool,
    /// Engine-side sync figures, read-only. Null when no replica is attached
    /// (or the engine cannot answer): absence is honest, never zeros. This
    /// never checkpoints; checkpointing is the engine's own job.
    pub sync: Option<SyncStats>,
    pub gate_rejections: u64,
    pub pulls_applied: u64,
    pub pulls_empty: u64,
    /// Unix seconds of the last pull attempt (0 = none yet).
    pub last_pull_unix: u64,
    /// Request telemetry since boot; the two probe routes are excluded so
    /// health checks cannot drown out real traffic. Latency buckets are
    /// fast < 25ms, ok < 100ms, slow >= 100ms.
    pub requests_ok: u64,
    pub requests_client_error: u64,
    pub requests_server_error: u64,
    pub in_flight: u64,
    pub latency_fast: u64,
    pub latency_ok: u64,
    pub latency_slow: u64,
}

#[derive(Serialize, utoipa::ToSchema)]
pub struct RowPage {
    pub cols: Vec<String>,
    pub rows: Vec<Vec<String>>,
}

/// What the sync engine reports about the local replica. Named fields, pinned
/// here so the store's turso type never crosses into the wire.
#[derive(Serialize)]
pub struct SyncStats {
    /// Local change-log operations the engine is tracking.
    pub cdc_operations: i64,
    pub main_wal_size: u64,
    pub revert_wal_size: u64,
    /// Null until the first successful sync of that direction.
    pub last_pull_unix: Option<i64>,
    pub last_push_unix: Option<i64>,
    pub revision: Option<String>,
    pub network_sent_bytes: usize,
    pub network_received_bytes: usize,
}

#[derive(serde::Deserialize)]
pub struct PrefixBody {
    pub prefix: String,
}

/// The caller's own key, as the key itself may see it. No hashes,
/// no secrets, no other keys, safe to hand to whoever presented it.
#[derive(Clone, Debug, serde::Serialize, utoipa::ToSchema)]
pub struct KeyInfo {
    pub prefix: String,
    pub admin: bool,
    pub scopes: Vec<String>,
}

/// The receipt for a state-changing key or role call. `ok` reports whether
/// the operation matched anything: deleting a key you do not own is `false`,
/// not an error.
#[derive(Serialize)]
pub struct Applied {
    pub ok: bool,
}

/// A freshly minted key, in plaintext and only once. The table keeps the
/// hash alone, so this response cannot be replayed.
#[derive(Serialize)]
pub struct NewKey {
    pub key: String,
}

/// What an admin is granting: a tier, plus the owner a commercial key belongs
/// to. Scopes are never named here: `store::accounts::create_key_spec` derives
/// them from the tier, so an admin cannot mint a half-granted key.
#[derive(serde::Deserialize)]
pub struct NewKeySpec {
    pub tier: String,
    /// Ignored for an admin key, which belongs to the staff, not to a user.
    #[serde(default)]
    pub owner: String,
}

/// A signed-in session. The token rides in the `Set-Cookie` header; the body
/// confirms it and names the role.
#[derive(Serialize)]
pub struct SignedIn {
    pub ok: bool,
    pub role: String,
}

/// One filed consumer report, as the admin surface lists it. `detail` may
/// be absent; the reporter is the key prefix that filed it.
#[derive(Clone, Debug, serde::Serialize, PartialEq)]
pub struct ReportSummary {
    pub id: String,
    pub target_type: String,
    pub target_id: String,
    pub reporter: String,
    pub reason: String,
    pub detail: Option<String>,
    pub created_at: i64,
}
