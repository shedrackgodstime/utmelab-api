//! MCP authentication — reserved, not enforced yet.
//!
//! Planned: two methods. Commercial callers present `x-api-key` under the
//! exact `Caller` rules (`resolve` → live-check → token spend). Admin/dev
//! callers present a separate credential (name + storage TBD). The decision
//! row lands before any enforcement here.

/// Header commercial MCP callers will present. Same wire as `/api/v1`.
pub const COMMERCIAL_HEADER: &str = "x-api-key";

/// Header admin/dev MCP callers will present. Name is provisional.
pub const ADMIN_HEADER: &str = "x-admin-key";
