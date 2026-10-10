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

    // The stored record must not carry the plaintext anywhere.
    let serialised = serde_json::to_string(&resolved).unwrap();
    assert!(!serialised.contains(&plaintext));
    assert!(!serialised.contains("sk_"));
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
