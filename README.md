# utmelab-api

Commercial question-bank API for JAMB/WAEC/NECO. One Rust binary serves the
metered API; Caddy serves the static docs tier alongside it. No Node process,
no SSR — see D32.

## Build and test

```bash
cargo build
cargo test                 # must be green before any push (113 tests)
cargo clippy --all-targets # must be clean
cargo fmt
cargo run -- openapi --out site/openapi.json  # after route/shape changes
```

## Run

```bash
cargo run -- serve                       # needs TURSO_DB_URL + TURSO_DB_TOKEN
cargo run -- key create --label my-laptop # prints the key once, never again
cargo run -- key list
cargo run -- key revoke --id <id>
cargo run -- key rotate --id <id>
cargo run -- import --dry-run             # merge data/inbox into the bank
cargo run -- quarantine                   # mechanical-defect report, read-only
cargo run -- audit-db                     # Turso table counts, read-only (R4)
```

Review is Python (no toolchain needed — works on any machine, human or agent):

```bash
python3 tools/review.py show <id> [--json]  # one question + everything related
python3 tools/review.py next [--subject s]  # lowest-id unverified, deterministic
python3 tools/review.py verify <id>         # refuses quarantined/explanationless
python3 tools/review.py set <id> [--subtopic S] [--underline W] [...]
python3 tools/review.py stats               # progress per subject
```

Config is environment only (`UTMELAB_API_BIND`, `UTMELAB_API_DATA_DIR`,
`TURSO_DB_URL`, `TURSO_DB_TOKEN`, … — see `src/config.rs`). The catalog and
novels are embedded in the binary; `UTMELAB_API_DATA_DIR` holds exactly
`questions.json` until questions move to Turso.

## Layout

| Path | What |
|---|---|
| `src/api/` | `/api/v1/*` (sold, key auth, in the spec) + `/internal/v1/*` (dashboard-only, never in the spec) |
| `src/bank/` | content core behind the `Store` trait — no HTTP, so routes never touch storage (D23) |
| `src/keys/` | API keys in Turso, CLI-administered, hash-only |
| `src/db/` | shared Turso handle + read-only `audit-db` (scaffolding, no migrations yet) |
| `src/reports/` | question-report intake (queue, not action) |
| `src/import.rs` | inbox → bank merge, three gates, every refusal counted (D51) |
| `src/quarantine.rs` | mechanical-defect scan: underline/image/dupes/leaks |
| `data/` | working copy: `questions.json` + catalog + `novels/` + `inbox/` staging |
| `site/` | static docs tier (Astro), built to `dist/` and shipped with the binary |
| `tools/` | harvester, syllabus importer, underline worksheet, review workbench |

## Decisions first

Nothing in `data/` changes until it is recorded in
`docs/QUESTION_BANK_DECISIONS.md` (D1–D63, PINNED/DEFERRED/REJECTED + grounds).
Start with `docs/HANDOFF.md` (the map), then the decision log (the law), then
`docs/TODO.md` (the work order). Open content defects live in
`docs/UNDERLINE_PROBLEM.md`.

## Deploy

One-time VPS setup, then one click per release — see
`docs/deployment/README.md`. Deploys never ship on plain push: Actions →
`deploy-api` → Run workflow (prerelease), or push a `v*` tag (release).
