//! Shared auth primitives. `api_key` guards the public surfaces
//! (`api` + `mcp`, same wire, same identity); `session` guards
//! `internal`. Levels are scopes on one identity — never duplicate routes.

pub mod api_key;
pub mod rate_limit;
pub mod session;

use crate::error::AppError;

/// The scope vocabulary is exactly what a route enforces. A scope is
/// declared here only when a handler calls [`Auth::require`] with it, so a
/// key's grant list can never name a capability nothing checks.
pub const SCOPE_READ_CATALOG: &str = "read:catalog";
pub const SCOPE_WRITE_REPORTS: &str = "write:reports";
pub const SCOPE_MANAGE_KEYS: &str = "manage:keys";

#[derive(Clone, Debug)]
pub struct Auth {
    pub key_id: String,
    pub is_admin: bool,
    pub scopes: Vec<String>,
}

impl Auth {
    pub fn has_scope(&self, scope: &str) -> bool {
        self.is_admin || self.scopes.iter().any(|s| s == scope)
    }

    pub fn require(&self, scope: &str) -> Result<(), AppError> {
        if self.has_scope(scope) {
            Ok(())
        } else {
            Err(AppError::Forbidden)
        }
    }
}
