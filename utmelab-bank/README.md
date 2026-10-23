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

Use `--json` for workflow output and `--dry-run` before a batch write.

## Configuration

Copy `.env.example` to `.env` and provide:

- a read-only production database URL and token for catalogue reads;
- the bank database URL and token for staging writes;
- media storage settings when figures are present;
- provider settings when using a model-backed task.

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
