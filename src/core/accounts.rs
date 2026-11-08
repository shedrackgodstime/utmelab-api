//! Account rules. Pure validation only; the tables live in `store`.

use super::validate;
use crate::error::AppError;

pub fn check_prefix(prefix: &str) -> Result<(), AppError> {
    if validate::ident(prefix) {
        Ok(())
    } else {
        Err(AppError::BadRequest("bad key prefix".to_string()))
    }
}

/// Roles the system understands. Anything else fails closed everywhere
/// roles are read: unknown means unauthorized, never a default.
pub fn check_role(role: &str) -> Result<(), AppError> {
    if matches!(role, "customer" | "admin" | "suspended") {
        Ok(())
    } else {
        Err(AppError::BadRequest("bad role".to_string()))
    }
}

/// Roles allowed to hold sessions. Suspended users authenticate fine but
/// receive nothing: the door stays shut at issuance, not just at use.
pub fn can_login(role: &str) -> bool {
    matches!(role, "customer" | "admin")
}

/// Tiers a key can hold. The tier fixes the scope grant (see
/// `store::accounts::create_key_spec`), so a caller names a tier and never a
/// scope list: a half-granted key is impossible by construction.
pub fn check_tier(tier: &str) -> Result<(), AppError> {
    if matches!(tier, "admin" | "commercial") {
        Ok(())
    } else {
        Err(AppError::BadRequest("bad tier".to_string()))
    }
}

/// Client token lifetimes. Five minutes is long enough for a page session and
/// short enough that a leaked token is not a standing grant; fifteen is the
/// ceiling, and the floor stops a client from minting in a tight loop.
pub const TOKEN_DEFAULT_TTL_SECS: u64 = 300;
pub const TOKEN_MAX_TTL_SECS: u64 = 900;
pub const TOKEN_MIN_TTL_SECS: u64 = 60;

/// The lifetime a mint request asks for, clamped to the policy. Absent means
/// the default; an out-of-range value is corrected rather than refused,
/// because the response always states the lifetime that was actually granted.
pub fn token_lifetime(requested: Option<u64>) -> u64 {
    requested
        .unwrap_or(TOKEN_DEFAULT_TTL_SECS)
        .clamp(TOKEN_MIN_TTL_SECS, TOKEN_MAX_TTL_SECS)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prefix_rules() {
        assert!(check_prefix("adm_1a2b").is_ok());
        assert!(check_prefix("").is_err());
        assert!(check_prefix("a b").is_err());
        assert!(check_prefix("a.b").is_err());
    }

    #[test]
    fn role_rules() {
        assert!(check_role("customer").is_ok());
        assert!(check_role("admin").is_ok());
        assert!(check_role("suspended").is_ok());
        assert!(check_role("").is_err());
        assert!(can_login("customer"));
        assert!(can_login("admin"));
        assert!(!can_login("suspended"));
    }

    #[test]
    fn tier_rules() {
        assert!(check_tier("admin").is_ok());
        assert!(check_tier("commercial").is_ok());
        assert!(check_tier("root").is_err());
        assert!(check_tier("").is_err());
    }

    /// The mint response states the granted lifetime, so the policy owns it
    /// and a request can never widen it past the ceiling.
    #[test]
    fn token_lifetime_is_clamped_to_policy() {
        assert_eq!(token_lifetime(None), TOKEN_DEFAULT_TTL_SECS);
        assert_eq!(token_lifetime(Some(1)), TOKEN_MIN_TTL_SECS);
        assert_eq!(token_lifetime(Some(300)), 300);
        assert_eq!(token_lifetime(Some(86_400)), TOKEN_MAX_TTL_SECS);
        assert_eq!(token_lifetime(Some(u64::MAX)), TOKEN_MAX_TTL_SECS);
    }
}
