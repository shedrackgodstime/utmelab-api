//! Ops, admin, and account shapes.
//!
//! These describe the service and the caller's own credentials, never bank
//! content: the wire forms behind the meta, status, and key surfaces.

use serde::Serialize;

#[derive(Serialize)]
pub struct TableRef {
    pub name: String,
}

#[derive(Serialize)]
pub struct ServiceStatus {
    pub service: &'static str,
    pub has_sync: bool,
    pub contract_ok: bool,
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

#[derive(Serialize)]
pub struct RowPage {
    pub cols: Vec<String>,
    pub rows: Vec<Vec<String>>,
}

#[derive(serde::Deserialize)]
pub struct PrefixBody {
    pub prefix: String,
}

/// The caller's own key, as the key itself may see it. No hashes,
/// no secrets, no other keys — safe to hand to whoever presented it.
#[derive(Clone, Debug, serde::Serialize)]
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

/// A signed-in session. The token rides in the `Set-Cookie` header; the body
/// confirms it and names the role.
#[derive(Serialize)]
pub struct SignedIn {
    pub ok: bool,
    pub role: String,
}
