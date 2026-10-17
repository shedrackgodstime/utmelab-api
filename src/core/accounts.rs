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
/// receive nothing — the door stays shut at issuance, not just at use.
pub fn can_login(role: &str) -> bool {
    matches!(role, "customer" | "admin")
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
}
