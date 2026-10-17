//! Observability vocabulary.
//!
//! One place for event and field names, so every call site spells them the
//! same way, the same discipline the rest of the crate applies to SQL and
//! predicates. Every audit event carries `event`, its subject fields, and a
//! final `outcome`, and it goes to the `audit` target, which can be filtered
//! or shipped on its own (`RUST_LOG=audit=info`). Operational logs stay on the
//! default target beside the request trace.
//!
//! Level policy: an operation that changed state logs at INFO; a refusal
//! (`denied`) or a privileged change that matched nothing (`not_found`) logs
//! at WARN, so it is alertable rather than silent.
//!
//! Rules:
//! - never log a secret (session token, password, raw API key) or a full
//!   answer;
//! - audit records decisions and lifecycle, not data. A customer write that
//!   persists its own attributed row (a report filing) is its own trail and is
//!   not duplicated here;
//! - `core` stays pure and logs nothing, so events fire at the edges;
//! - a key actor is labelled `key:<prefix>` so an actor is never ambiguous
//!   between a dashboard username and an API key.

/// Sign-in succeeded; `role` is the session role that was minted.
pub fn login_ok(user: &str, role: &str) {
    tracing::info!(target: "audit", event = "login", user = user, role = role, outcome = "ok");
}

/// Sign-in was refused. `reason` is a small fixed set: `bad_credentials`,
/// `rate_limited`, or `error`.
pub fn login_denied(user: &str, reason: &str) {
    tracing::warn!(target: "audit", event = "login", user = user, reason = reason, outcome = "denied");
}

/// Audit an operation that reports whether it changed anything. A privileged
/// change that matched nothing still gets a line, at WARN, so a probe or a
/// fat-fingered revoke is never silent.
macro_rules! audit_applied {
    ($applied:expr, $($field:tt)+) => {
        if $applied {
            tracing::info!(target: "audit", $($field)+, outcome = "ok");
        } else {
            tracing::warn!(target: "audit", $($field)+, outcome = "not_found");
        }
    };
}

/// An API key was minted. Only the prefix is recorded; the secret exists once,
/// in the response, and is never logged.
pub fn key_created(actor: &str, prefix: &str, tier: &str) {
    tracing::info!(target: "audit", event = "key.create", actor = actor, prefix = prefix, tier = tier, outcome = "ok");
}

/// A customer deleted one of their keys. A prefix that was not theirs reports
/// `not_found`, so a probe of someone else's key is visible without an error.
pub fn key_deleted(actor: &str, prefix: &str, found: bool) {
    audit_applied!(found, event = "key.delete", actor = actor, prefix = prefix);
}

/// An admin revoked or restored a key. `applied` is false when no such prefix
/// existed, which is still worth a line.
pub fn key_revoked(actor: &str, prefix: &str, revoked: bool, applied: bool) {
    audit_applied!(
        applied,
        event = "key.revoke",
        actor = actor,
        prefix = prefix,
        revoked = revoked
    );
}

/// An admin changed a user's role. `applied` is false when no such user.
pub fn role_changed(actor: &str, user: &str, role: &str, applied: bool) {
    audit_applied!(
        applied,
        event = "user.role",
        actor = actor,
        user = user,
        role = role
    );
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
    fn every_audit_event_carries_target_event_and_outcome() {
        let buf = Buffer::default();
        let subscriber = tracing_subscriber::fmt()
            .with_writer(buf.clone())
            .with_ansi(false)
            .finish();
        tracing::subscriber::with_default(subscriber, || {
            login_ok("alice", "admin");
            login_denied("bob", "bad_credentials");
            key_created("alice", "abc123", "commercial");
            key_deleted("alice", "abc123", true);
            key_revoked("root", "deadbeef", true, false);
            role_changed("root", "bob", "admin", true);
        });
        let out = String::from_utf8(buf.0.lock().expect("lock").clone()).expect("utf8");

        assert_eq!(
            out.matches("audit").count(),
            6,
            "every event carries the audit target: {out}"
        );
        for event in [
            "event=\"login\"",
            "event=\"key.create\"",
            "event=\"key.delete\"",
            "event=\"key.revoke\"",
            "event=\"user.role\"",
        ] {
            assert!(out.contains(event), "missing {event}: {out}");
        }
        assert!(out.contains("outcome=\"ok\""), "{out}");
        assert!(out.contains("outcome=\"denied\""), "{out}");
        assert!(
            out.contains("outcome=\"not_found\""),
            "a no-op privileged change must not be silent: {out}"
        );
    }
}
