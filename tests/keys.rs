//! Key-store behaviour. These are the guarantees a paying customer's access
//! depends on, so they are integration tests against the real store type.

use std::path::PathBuf;

use utmelab_api::KeyStore;

/// A private, uniquely-named store per test — the harness runs these in
/// parallel, so a shared path would have them fighting over one file.
fn store(name: &str) -> (KeyStore, PathBuf) {
    let path =
        std::env::temp_dir().join(format!("utmelab-keys-{}-{name}.json", std::process::id()));
    let _ = std::fs::remove_file(&path);
    (KeyStore::open_json(&path).expect("temp store"), path)
}

#[test]
fn created_key_resolves_and_carries_no_secret() {
    let (mut s, _) = store("resolve");
    let (record, plaintext) = s.create("test", 10).expect("create");

    assert!(plaintext.starts_with("sk_"));
    assert_eq!(plaintext.len(), 3 + 64, "sk_ plus 32 bytes of hex");

    let resolved = s.resolve(&plaintext).expect("key must resolve");
    assert_eq!(resolved.id, record.id);
    assert_eq!(resolved.label, "test");
    assert_eq!(resolved.rate_limit, 10);

    // The stored record must not carry the plaintext anywhere. `key_prefix`
    // (first 11 chars) IS a fragment of it by design — support lookup only,
    // it never authenticates (D53) — so the blanket "no sk_" check from
    // before the prefix existed is now: full plaintext absent, prefix short.
    let serialised = serde_json::to_string(&resolved).unwrap();
    assert!(!serialised.contains(&plaintext), "full plaintext must never appear");
    for fragment in serialised.split('"').filter(|s| s.starts_with("sk_")) {
        assert!(fragment.len() <= 11, "only the 11-char prefix may appear: {fragment}");
    }
}

#[test]
fn unknown_and_revoked_keys_are_indistinguishable() {
    let (mut s, _) = store("revoke");
    let (record, plaintext) = s.create("test", 10).expect("create");

    assert!(s.resolve("sk_deadbeef").is_none());
    assert!(s.revoke(&record.id).expect("revoke"));
    assert!(
        s.resolve(&plaintext).is_none(),
        "revoked key must not resolve"
    );
    assert!(!s.revoke(&record.id).expect("second revoke is a no-op"));
}

#[test]
fn expired_keys_do_not_resolve_but_stay_listed() {
    use utmelab_api::KeyStatus;

    let (mut s, _) = store("expiry");
    let (record, plaintext) = s.create("old", 10).expect("create");
    assert!(s.resolve(&plaintext).is_some());

    // Rotate with zero grace: old key expires immediately.
    let (successor, new_plaintext) = s
        .rotate(&record.id, 0)
        .expect("rotate")
        .expect("old key was live");
    assert_ne!(successor.id, record.id);
    assert!(s.resolve(&new_plaintext).is_some());

    let rows = s.list();
    let old = rows.iter().find(|k| k.id == record.id).expect("old listed");
    assert_eq!(old.status(), KeyStatus::Expired);
    assert!(!old.is_live());
    assert!(
        s.resolve(&plaintext).is_none(),
        "expired key must not resolve"
    );
}

#[test]
fn rotation_returns_none_for_unknown_or_dead_keys() {
    let (mut s, _) = store("rotate-none");
    assert!(s.rotate("key_nope", 24).expect("rotate").is_none());

    let (record, _) = s.create("gone", 10).expect("create");
    assert!(s.revoke(&record.id).expect("revoke"));
    assert!(s.rotate(&record.id, 24).expect("rotate").is_none());
}

#[test]
fn list_shows_every_key_with_status_and_no_secrets() {
    let (mut s, _) = store("list");
    let (a, a_plain) = s.create("first", 10).expect("create");
    let (b, _) = s.create("second", 20).expect("create");
    assert!(s.revoke(&b.id).expect("revoke"));

    let rows = s.list();
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].id, a.id);
    assert_eq!(rows[1].id, b.id);
    for row in &rows {
        assert_eq!(row.account_id, "local");
        assert_eq!(row.plan, "free");
        assert!(
            row.key_prefix
                .as_deref()
                .is_some_and(|p| p.starts_with("sk_"))
        );
        let serialised = serde_json::to_string(row).unwrap();
        assert!(!serialised.contains(&a_plain));
        assert!(!serialised.contains("key_hash"));
    }
    assert!(rows[0].is_live());
    assert!(!rows[1].is_live());
}

#[test]
fn a_cli_change_is_visible_after_reload() {
    let (mut s, path) = store("reload");
    let (record, plaintext) = s.create("live", 10).expect("create");
    assert!(s.resolve(&plaintext).is_some());

    // Another process (the CLI) revokes behind our back.
    let mut other = KeyStore::open_json(&path).expect("reopen");
    assert!(other.revoke(&record.id).expect("revoke"));

    // We still see the stale state until we reload — then it lands.
    assert!(s.resolve(&plaintext).is_some(), "stale until reload");
    assert!(s.reload_if_changed().expect("reload"));
    assert!(
        s.resolve(&plaintext).is_none(),
        "revoke visible without restart"
    );
    assert!(!s.reload_if_changed().expect("second reload is a no-op"));
}

#[test]
fn distinct_keys_get_distinct_digests() {
    let (mut s, _) = store("distinct");
    let (_, a) = s.create("a", 10).expect("create");
    let (_, b) = s.create("b", 10).expect("create");
    assert_ne!(a, b);
    assert_eq!(s.count(), 2);
}

#[test]
fn keys_survive_a_reopen() {
    let (mut s, path) = store("persist");
    let (record, plaintext) = s.create("durable", 42).expect("create");

    let reopened = KeyStore::open_json(&path).expect("reopen");
    let resolved = reopened.resolve(&plaintext).expect("must survive restart");
    assert_eq!(resolved.id, record.id);
    assert_eq!(resolved.rate_limit, 42);
}
