//! Input shape rules. Pure predicates shared by every surface and the
//! store: one spelling for "safe identifier", unit-tested here.

/// ASCII alphanumerics plus underscore, 1 to 64 chars. Anything else is
/// rejected before it touches SQL, paths, or filenames.
pub fn ident(s: &str) -> bool {
    !s.is_empty() && s.len() <= 64 && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_plain_names() {
        assert!(ident("probe_sync"));
        assert!(ident("adm_1a2b"));
        assert!(ident("a1_"));
    }

    #[test]
    fn rejects_injection() {
        assert!(!ident(""));
        assert!(!ident("a b"));
        assert!(!ident("a.b"));
        assert!(!ident("t\" OR 1=1 --"));
        assert!(!ident(&"x".repeat(65)));
    }
}
