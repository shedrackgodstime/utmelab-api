# `src/mcp/` — MCP surface (prototype scaffold)

No behaviour yet. This directory reserves the shape so the **auth decision
lands first** and every later tool/resource has one place to live.

## Layout

| File | What |
|---|---|
| `mod.rs` | Module root + empty `router()` (merges `tools` + `resources`) |
| `auth.rs` | Reserved header names (`x-api-key` commercial, `x-admin-key` provisional). No enforcement. |
| `tools.rs` | Reserved. Callable operations land here, after auth. |
| `resources.rs` | Reserved. Read-only URI views land here, after auth. |

## Rules for what lands here

1. **Auth first.** Two methods are planned — commercial API key (same
   `Caller` rules as `/api/v1`: resolve → live-check → token spend) and an
   admin/dev credential — but names, storage, and failure modes are
   **undecided**. Nothing enforces anything until the decision row exists.
2. **Thin projections only.** Tools/resources read through `AppState`
   (the same `Store` methods the routes call). No new storage, no new key
   type, no changes to `bank/`/`keys/`.
3. **Same commercial rules.** Paged (≤200), answers withheld unless opted
   in, 401/429 shapes identical to `/api/v1`.
4. **No `crates/`.** MCP lives in this binary (one deploy, one process —
   D29/D32). The empty `crates/mcp/` directory is retired.

## Build

```bash
cargo build
cargo test                 # must be green before any push
cargo clippy --all-targets # must be clean
cargo fmt
```
