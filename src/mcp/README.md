# `src/mcp/` — MCP surface (prototype scaffold)

Two separate things, not one surface with two logins:

- **Commercial.** Same access the API key allows — catalog, questions,
  search, paging — under the exact `Caller` rules (resolve → live-check →
  token spend, answers withheld unless opted in). Nothing more.
- **Admin.** Beyond the API: list, manage, update, and alter the full bank
  over the wire — pull unverified questions with their topic and relations,
  review, retag, edit, attach explanations, and record a review verdict — so
  reviewers (human or AI) can work the bank without touching the codebase or
  the JSON files. This is the ingest/review pipeline for the long tail, where
  the work is split across many reviewers and no single human or AI can do
  it alone. **What "record a verdict" is allowed to mean is set by D62, not by
  this file** — see rule 3.

No behaviour yet. This directory reserves the shape so the **auth decision
lands first** and every later tool/resource has one place to live.

## Layout

| File | What |
|---|---|
| `mod.rs` | Module root + empty `router()` (merges `tools` + `resources`) |
| `auth.rs` | Reserved header names (`x-api-key` commercial, `x-admin-key` provisional). No enforcement. |
| `tools.rs` | Reserved. Commercial tools (read-only) and admin tools (bank writes) land here, after auth. |
| `resources.rs` | Reserved. Commercial resources (read-only views) and admin resources (review queues, unverified sets) land here, after auth. |

**Mount point: `/mcp`**, served from this binary at `api.utmelab.com/mcp`.
Note it is *not wired yet* — `lib.rs` merges `mcp::router()` bare, where
`api::router()` nests `/api` and `/internal`. `mod.rs` gains
`.nest("/mcp", …)` when the first route lands, so no tool can ship at an
un-nested path by accident.

## Rules for what lands here

1. **Auth first.** Two methods are planned — commercial API key (same
   `Caller` rules as `/api/v1`: resolve → live-check → token spend) and an
   admin/dev credential — but names, storage, and failure modes are
   **undecided**. Nothing enforces anything until the decision row exists.
2. **Commercial = thin read-only projections.** Same `Store` reads the
   routes call, paged (≤200), answers withheld unless opted in, 401/429
   shapes identical to `/api/v1`. No new storage, no new key type.
3. **Admin = managed bank writes — and D62 bounds what that means.** Retag,
   edit, explanations, verify: these need write paths the API never had, so
   they will touch `bank/` / verification storage by design, behind the admin
   credential only. Commercial keys can never reach them.

   **"Verify" is not a privilege the admin surface grants, it is a log row.**
   Per D62, `verified=true` is set by exactly one thing: a `Human/Pass`
   verification covering `{Answer, Explanation}` whose `content_hash` still
   matches. An `AutoRule` row can only *block* verification — a quarantined
   row is never verified whoever passed it. `AiSingle` and `AiBulk` **write
   signal rows and never flip the bool**, so an AI reviewer working this
   surface records findings (`AiSingle`, with scope) and leaves `verified`
   to a human. If a tool here can set `verified` directly, it is a bug in the
   tool, not a feature of the admin tier.

   Corollary the write path inherits: any edit to text, options, answer,
   marks or explanation changes `content_hash` and **voids that row's
   existing pass** (`human_verified` is strict equality). That is correct
   behaviour — but it means an admin write is never a silent content change,
   and the void should be explainable from the log.

4. **No `crates/`.** MCP lives in this binary — one deploy, one process
   (D32: the web tier is static files, forever; no Node, no SSR). The scraper
   stays Python and reads `data/*.json`; the dashboard is a route group in
   this binary. One binary, one consumer of `bank/`, so a workspace would
   restructure the tree and change nothing a caller sees.

## Build

```bash
cargo build
cargo test                 # must be green before any push
cargo clippy --all-targets # must be clean
cargo fmt
```
