# UTME Lab API

The UTME Lab API is the public API for exam preparation content. The repository
also contains the content bank used to prepare and review material before it is
served by the API.

## GitHub Actions workflows

These are the active workflows in `.github/workflows/`:

| Workflow | Purpose |
| --- | --- |
| `quality.yml` | CI checks for Rust, the site, and `utmelab-bank`. |
| `bank.yml` | Content-bank operations such as fetching, processing, reviewing, and handing off content. |
| `deploy.yml` | Builds and deploys the API and documentation site. |
| `uptime.yml` | Checks that the public API edge is serving correctly. |

The bank workflow prepares content. It does not deploy the API. The deploy
workflow ships the API and site. The uptime workflow checks the public result
from outside the server.

## Project areas

- `crates/`: Rust API and domain code.
- `site/`: Documentation and public site.
- `utmelab-bank/`: Content preparation tool and its tests.
- `.github/workflows/`: CI, bank operations, deployment, and monitoring.

See [`utmelab-bank/README.md`](utmelab-bank/README.md) for the content-bank
workflow and operating boundary.
