# UTME Lab API

The UTME Lab API is the public API for exam preparation content. It serves
books, chapters, sections, exercises, recall checks, and exam traps from a
local SQLite replica.

The content bank and the textbook factory live in their own repository:
[shedrackgodstime/utmelab-bank](https://github.com/shedrackgodstime/utmelab-bank).
This repository holds the Rust service, the public site, and the deployment
machinery. It does not hold the content pipeline or the authored content.

## GitHub Actions workflows

These are the active workflows in `.github/workflows/`:

| Workflow | Purpose |
| --- | --- |
| `quality.yml` | CI checks for Rust and the static site. |
| `deploy.yml` | Builds and deploys the API and documentation site from a published release. |
| `uptime.yml` | Checks that the public API edge is serving correctly. |

The deploy workflow ships the API and site. The uptime workflow checks the
public result from outside the server. Content work, including the content
gate, runs in the content repository.

## Project areas

- `src/`: Rust API, domain, authentication, storage, and server code.
- `site/`: Documentation and public site.
- `docs/`: Architecture, ADRs, deployment, and sync recovery.
- `scripts/live-benchmark.sh`: HTTP benchmark against a running server.
- `.github/workflows/`: CI, deployment, and monitoring.

## Content boundary

Textbooks belong to no exam. The content repository builds them, validates
them, and hands a bundle to the API's `import-chapters` command. The API reads
the bundle into its database; it never reads the content repository at build
time or at request time.

The GitLab project `shedrackgodstime/utmelab-bank` stores the published images
under `images/` and `books/`. It is separate from both code repositories.
