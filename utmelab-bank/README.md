# UTME Lab Bank

`utmelab-bank` prepares exam content for the serving API.

It reads content from a source, converts it to the bank shape, rejects bad or
duplicate rows, places accepted rows against the production catalogue, adds
explanations and media, reviews the result, and reports whether the row is
ready for future production placement.

The bank owns staging and review work. It does not serve HTTP responses, write
the production content tables, manage learner progress, or handle billing.

## The active workflow

```text
fetch -> capture -> tag -> media -> explain -> review -> ready
```

`fetch` can capture source figures while the source is available. The separate
`capture` command resumes that work for rows left in `deduped`. The remaining
commands operate on the next legal state and can be rerun safely.

The `process` preset runs:

```text
capture -> tag -> media -> explain -> review -> ready
```

Run `fetch` first. Use `process` after the source rows reach `deduped`.

## Common commands

Install the development tools from this directory:

```bash
pip install -e ".[dev]"
```

List the available tasks:

```bash
utmelab-bank tasks
```

Fetch fixture content without writing:

```bash
utmelab-bank fetch \
  --source fixture \
  --exam JAMB \
  --subject biology \
  --year 2024 \
  --dry-run
```

Fetch live source content:

```bash
utmelab-bank fetch \
  --source myschool \
  --exam JAMB \
  --subject biology \
  --year 2024 \
  --limit 100
```

Process accepted rows with the selected provider:

```bash
utmelab-bank process \
  --exam JAMB \
  --subject biology \
  --year 2024 \
  --provider mock
```

Inspect the bank and index:

```bash
utmelab-bank status
```

Inspect either database without a token on the command line:

```bash
utmelab-db status
utmelab-db items --state deduped --limit 20
utmelab-db --database prod query "SELECT exam, COUNT(*) FROM subjects GROUP BY exam"
utmelab-db --database prod catalog
```

`utmelab-db --database prod catalog` checks the production catalog against the
rules tagging depends on: every topic and subtopic has a name, every subtopic
names a real topic, and every subject has topics. Blank names and orphans fail
the command; coverage gaps (subjects with no topics, topics with no subtopics)
are reported as warnings, and `--strict` makes them fail too. The batch workflow
runs this before every task.

`utmelab-db` reads the same `.env` as the pipeline, and refuses every
statement that is not a read. For a question it does not answer, import the
library in a script instead of building a Turso connection:

```python
import asyncio

from utmelab_bank.db import open_database


async def main() -> None:
    async with open_database("bank") as db:
        result = await db.query(
            "SELECT state, COUNT(*) AS rows FROM staging_items GROUP BY state"
        )
        print(result.as_dicts())


asyncio.run(main())
```

Use `--json` for workflow output and `--dry-run` before a batch write. A batch
task stops after three consecutive failures by default, so a provider that has
run out of quota cannot keep the run going row after row; change that with
`--max-failures`, or pass `0` to remove the cap.

## Configuration

Copy `.env.example` to `.env` and provide:

- a read-only production database URL and token for catalogue reads;
- the bank database URL and token for staging writes;
- media storage settings when figures are present;
- provider settings when using a model-backed task.

Provider and model routing lives in `config/`. Each file under
`config/providers/` describes one provider family (`openai.json` for
OpenAI-compatible endpoints, `opencode.json` for the OpenCode CLI) and contains
no secrets. `config/routing.json` maps each task to provider/model candidates in
priority order, so changing a default is a config edit, not a Python edit. A
manifest names environment variables, account pools, model capabilities,
protocols, transports, and account status. The shared schemas are
`config/schema/provider.schema.json` and `config/schema/routing.schema.json`,
and the contract suite validates every manifest and the routing file before a
batch is allowed to proceed.

The routing file lists accounts in failover order. The ``config`` provider
now tries each route in order, failing over on retryable errors
(rate_limit, quota, timeout, provider_unavailable, upstream, transport).
Non-retryable errors (authentication, invalid_request, input, output,
schema, policy, not_found) never rotate accounts or hide the original
defect.

The routing file is the integration point for text and image work. Provider
protocols select the adapter (`openai-compatible` for HTTP, `opencode-cli` for
the CLI), and the two-witness image consensus reads the same candidates.

A wheel ships a copy of `config/` at `utmelab_bank/config_data/`, so an
installed CLI runs without the source tree. Set `UTMELAB_BANK_CONFIG_DIR`
to point at an editable copy when you need to change routes without rebuilding.

The CLI also uses `UTMELAB_BANK_VAR_DIR` for its working directory and
`UTMELAB_BANK_ENV_FILE` to locate the `.env` file. In a source checkout
these default to `utmelab-bank/var` and `utmelab-bank/.env`. In an installed
wheel they default to XDG directories (`~/.local/share/utmelab-bank/var`
and `~/.config/utmelab-bank/.env`), with a fallback to a `.env` in the
current working directory.

The production token must be read-only. The bank must never write the serving
API's content tables.

## Development checks

Run these from `utmelab-bank/`:

```bash
ruff format --check src tests
ruff check src tests
mypy src/utmelab_bank
pytest -m "not live"
```

Live tests are opt-in because they use real services or command-line tools.
Archived projects under `archive/` are reference material and are not part of
the active test suite.

## Output boundary

`ready` is the current output boundary. It records the checks and state needed
for future production placement. The bank does not write the serving database
or upload content artifacts to GitHub.
