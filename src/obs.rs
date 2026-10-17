//! Observability vocabulary.
//!
//! One place for event and field names, so every call site spells them the
//! same way, the same discipline the rest of the crate applies to SQL and
//! predicates. Security and business events go to the `audit` target, which
//! can be filtered or shipped on its own (`RUST_LOG=audit=info`); operational
//! logs stay on the default target beside the request trace.
//!
//! Rules:
//! - never log a secret (session token, password, raw API key) or a full
//!   answer;
//! - `core` stays pure and logs nothing, so events fire at the edges;
//! - a key actor is labelled `key:<prefix>` so an actor is never ambiguous
//!   between a dashboard username and an API key.

/// Sign-in succeeded; `role` is the session role that was minted.
pub fn login_ok(user: &str, role: &str) {
    tracing::info!(target: "audit", event = "login", outcome = "ok", user = user, role = role);
}

/// Sign-in was refused. `reason` is a small fixed set: `bad_credentials`,
/// `rate_limited`, or `error`.
pub fn login_denied(user: &str, reason: &str) {
    tracing::warn!(target: "audit", event = "login", outcome = "denied", user = user, reason = reason);
}

/// An API key was minted. Only the prefix is recorded; the secret exists once,
/// in the response, and is never logged.
pub fn key_created(actor: &str, prefix: &str, tier: &str) {
    tracing::info!(target: "audit", event = "key.create", actor = actor, prefix = prefix, tier = tier);
}

/// A customer deleted one of their keys. `found` is false when the prefix was
/// not theirs, so a probe of someone else's key is visible without an error.
pub fn key_deleted(actor: &str, prefix: &str, found: bool) {
    tracing::info!(target: "audit", event = "key.delete", actor = actor, prefix = prefix, found = found);
}

/// An admin revoked or restored a key.
pub fn key_revoked(actor: &str, prefix: &str, revoked: bool) {
    tracing::info!(target: "audit", event = "key.revoke", actor = actor, prefix = prefix, revoked = revoked);
}

/// An admin changed a user's role.
pub fn role_changed(actor: &str, user: &str, role: &str) {
    tracing::info!(target: "audit", event = "user.role", actor = actor, user = user, role = role);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::sync::{Arc, Mutex};

    /// Shared sink so a test can read back what the subscriber wrote.
    #[derive(Clone, Default)]
    struct Buffer(Arc<Mutex<Vec<u8>>>);

    impl Write for Buffer {
        fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
            self.0
                .lock()
                .map_err(|_| std::io::Error::other("buffer lock"))?
                .extend_from_slice(buf);
            Ok(buf.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }

    impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for Buffer {
        type Writer = Buffer;
        fn make_writer(&'a self) -> Self::Writer {
            self.clone()
        }
    }

    #[test]
    fn audit_events_carry_target_and_fields() {
        let buf = Buffer::default();
        let subscriber = tracing_subscriber::fmt()
            .with_writer(buf.clone())
            .with_ansi(false)
            .finish();
        tracing::subscriber::with_default(subscriber, || {
            login_denied("alice", "bad_credentials");
            key_created("alice", "abc123", "commercial");
        });
        let out = String::from_utf8(buf.0.lock().expect("lock").clone()).expect("utf8");
        assert!(out.contains("audit"), "must carry the audit target: {out}");
        assert!(out.contains("event=\"login\""), "{out}");
        assert!(out.contains("outcome=\"denied\""), "{out}");
        assert!(out.contains("bad_credentials"), "{out}");
        assert!(out.contains("event=\"key.create\""), "{out}");
        assert!(out.contains("tier=\"commercial\""), "{out}");
    }
}
