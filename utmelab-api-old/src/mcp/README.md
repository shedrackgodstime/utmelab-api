# `src/mcp/` — MCP surface (prototype scaffold)

**Status: shape only. No routes, no tools, no resources, no behaviour.**

Nothing in this directory is decided, and this file is not the place it gets
decided. Answers go in `docs/QUESTION_BANK_DECISIONS.md` as a row, before any
code lands (D7). Nothing here is law.

## What it is for

Two purposes, deliberately not one surface:

- **Commercial.** An MCP view of what an API key already allows — catalog,
  questions, search, paging — for consumers who want the bank reachable from
  an AI assistant.
- **Owner.** The bank worked from a phone: pull questions, review them, fix
  them, without the codebase, the toolchain, or the JSON files.

The second exists because reviewing content needs a device, and the device in
use does not run the toolchain. That is the whole reason the surface is wanted.

## What exists now

| File | What |
|---|---|
| `mod.rs` | Module root, empty `router()` merging `tools` + `resources` |
| `auth.rs` | Placeholder module. No behaviour. |
| `tools.rs` | Empty router |
| `resources.rs` | Empty router |

`lib.rs` merges `mcp::router()` at the top level. There are no routes, so the
surface is unreachable today; the merge exists so the first route does not
also have to touch `lib.rs`.

## Not decided

Deliberately, and all of it:

- **How each surface authenticates**, and whether they share a credential or
  have their own.
- **Which operations each surface may perform**, and what may write to the bank
  at all.
- **What a review verdict is allowed to mean.** `verified` is derived from the
  verification log under D62: only a human pass sets it, and AI rows are
  signal only. Whichever credential is used must not be able to assert a human
  review that did not happen. That constrains the auth shape, so it gets
  answered before auth does.
- **The mount path.** Nothing is registered, so the router pins nothing.

## Build

```bash
cargo build
cargo test                 # must be green before any push
cargo clippy --all-targets # must be clean
cargo fmt
```