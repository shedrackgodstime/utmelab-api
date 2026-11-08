//! Shared auth primitives. `api_key` guards the public surfaces
//! (`api` + `mcp`, same wire, same identity); `session` guards
//! `internal`. Levels are scopes on one identity, never duplicate routes.

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

/// Which wire credential produced this identity. The authority is the same
/// either way; the kind only answers "may this caller mint a token?".
/// Secrets may; tokens may not.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Credential {
    Secret,
    Token,
}

#[derive(Clone, Debug)]
pub struct Auth {
    /// The owning key prefix. A token resolves to its parent, so quota and
    /// audit always name the developer account, never the individual token.
    pub key_id: String,
    pub is_admin: bool,
    pub scopes: Vec<String>,
    pub credential: Credential,
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
