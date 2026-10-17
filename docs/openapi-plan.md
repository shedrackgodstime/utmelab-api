# OpenAPI plan (deferred)

## Problem

`site/openapi.json` is hand-written and already lies about the API:

- It omits real routes: `/api/v1/meta/tables`, `/api/v1/meta/rows/{table}`, `/api/internal/*`, all MCP tools/resources.
- It invents a route that does not exist: `GET /openapi.json`.
- It uses hardcoded example values instead of path templates (`{exam}`).

That is a regression: a false spec is worse than no spec.

## Principle

Derive the spec from code, not by hand. Put `#[derive(ToSchema)]` on handler return types in `core/models/wire.rs` and `core/models/admin.rs`. A field cannot exist in JSON but be missing in code.

## Approach

1. Add `utoipa` to the root `Cargo.toml`.
2. Add `#[derive(ToSchema)]` to response models in `core/models/`.
3. Build the spec in a `#[test]` and diff it against `site/openapi.json`; regenerate `site/openapi.json` from code.
4. Optionally serve `GET /openapi.json` if clients need to fetch it live.
5. Delete the hand-written `site/openapi.json`.

## Not a CLI verb

No `openapi --out` command. The spec is enforced by `cargo test`, not by a manual step. This keeps the CLI minimal: run the server, or `seed-admin`.

## Test contract

Every route in `src/routes/mod.rs` must appear in the spec, and every path in the spec must exist in `routes/mod.rs`. Response bodies must match `ToSchema` output.

## Status

Deferred. Honest absence is better than a false presence until this is implemented.
