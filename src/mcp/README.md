# `src/mcp/` — MCP surface (prototype scaffold)

Two separate things, not one surface with two logins:

- **Commercial.** Same access the API key allows — catalog, questions,
  search, paging — under the exact `Caller` rules (resolve → live-check →
  token spend, answers withheld unless opted in). Nothing more.
- **Admin.** Beyond the API: list, manage, update, and alter the full bank
  over the wire — pull unverified questions with their topic and relations,
  review, retag, edit, attach explanations, mark verified — so reviewers
  (human or AI) can work the bank without touching the codebase or the
  JSON files. This is the ingest/review pipeline for 100k+ questions, where
  the work is split across many reviewers and no single human or AI can do
  it alone.

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
