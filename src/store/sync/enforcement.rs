//! Source-level tripwires for the sync boundary.
//!
//! The type system is the primary guard: the raw handle is private to
//! [`super::engine::Engine`] and every engine method requires a budget. These
//! tests catch the leaks the type system cannot see, such as a re-export, a
//! raw call hidden behind a helper, or a new sync knob that nobody documented.
//!
//! A failure here is a design review, not a test to silence. Move the code
//! behind the boundary or add the missing documentation.

use std::path::{Path, PathBuf};

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn rust_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            rust_files(&path, out);
        } else if path.extension().and_then(|e| e.to_str()) == Some("rs") {
            out.push(path);
        }
    }
}

fn relative(path: &Path) -> String {
    path.strip_prefix(root())
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

fn source(path: &Path) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()))
}

/// The tripwire file names its own forbidden patterns, so it never scans
/// itself. Every other source file is in scope.
fn scanned_files() -> Vec<PathBuf> {
    let mut files = Vec::new();
    rust_files(&root().join("src"), &mut files);
    files.retain(|path| relative(path) != "src/store/sync/enforcement.rs");
    files
}

#[test]
fn raw_engine_operations_live_only_in_the_engine() {
    let allowed = "src/store/sync/engine.rs";
    for path in scanned_files() {
        if relative(&path) == allowed {
            continue;
        }
        let text = source(&path);
        for needle in [".db.pull(", ".db.push(", ".db.stats(", ".db.connect("] {
            assert!(
                !text.contains(needle),
                "{} reaches the raw engine with {needle}; add an Engine method with a budget",
                relative(&path)
            );
        }
    }
}

#[test]
fn the_engine_crate_is_imported_only_by_the_store() {
    for path in scanned_files() {
        let relative = relative(&path);
        if relative.starts_with("src/store/") || relative == "src/testing.rs" {
            continue;
        }
        let text = source(&path);
        assert!(
            !text.contains("turso::"),
            "{relative} imports the engine; the store owns that boundary"
        );
    }
}

#[test]
fn the_contract_flag_cannot_be_toggled_outside_readiness() {
    for path in scanned_files() {
        let text = source(&path);
        assert!(
            !text.contains("contract_ok.store") && !text.contains("contract_ok.swap"),
            "{} toggles a contract flag; readiness is derived from SyncState",
            relative(&path)
        );
    }
}

#[test]
fn every_sync_environment_variable_is_documented() {
    let config = source(&root().join("src/config.rs"));
    let example = source(&root().join(".env.example"));
    let mut missing = Vec::new();
    for line in config.lines() {
        let line = line.trim();
        let Some(rest) = line.strip_prefix('"') else {
            continue;
        };
        let Some(end) = rest.find('"') else {
            continue;
        };
        let key = &rest[..end];
        if key.starts_with("SYNC_") && !example.contains(key) {
            missing.push(key.to_string());
        }
    }
    missing.sort();
    missing.dedup();
    assert!(
        missing.is_empty(),
        "sync variables missing from .env.example: {missing:?}"
    );
}
