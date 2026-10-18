# utmelab-bank ROADMAP

The plan of record for the bank. Two jobs:

1. **The agreement.** What we decided, in the words we decided it, so a later
   session cannot quietly re-scope the work.
2. **The roadmap.** Ordered steps, each provable on its own, each with a green
   definition. We prove them one at a time until all are green.

The `README.md` next to this file is the **design reference** (how the pieces
fit). This file is the **plan and the status truth**. When they disagree about
status, this file wins and the README gets fixed.

## The agreement (do not re-scope these)

### Boundaries

- The bank has **its own database**, isolated from production. It stages into
  `raw_` / `work_` / `ready_` lane tables inside that database.
- **Moving `ready_*` rows into the production database is out of scope.** How
  the data leaves the bank and reaches production is somebody else's job. We
  stop at "clean, rich, ready, and hash-correct."
- "Put it on production" means **deploy the bank so it starts working**: running
  unattended, filling its own database, making measurable progress. It does not
  mean writing the serving database.
- The last human verification before content is served is **beyond our scope**.
  Our job is to make it so clean that that final pass needs little or no work.
- `tools/` and `utmelab-pipeline/` are **reference only**. They are prototypes
  we are retiring. They are read for ideas and for porting, never edited.

### Shape of the thing

- Flows are **independent**. Each task runs alone (`scrape` without gating,
  `ai-explain --where 'no explanation'` without touching a token for anything
  else). Composition is written **last**, as a `goal` over tasks that already
  work alone. No task calls another task.
- The selector vocabulary is the glue: `no explanation`, `unverified`,
  `no subtopic`, `no description`, `no blob`, `not uploaded`, `gated`,
  `retryable`, `has images`, `run=N`, `id=...`.
- **Sources are plugins.** Add one by writing a module and one line in the
  source registry. Each declares what it can fetch (`catalog`, `media`, exams).
- **AI providers are plugins.** One interface, `complete(prompt) -> str`, one
  line to add a backend. The model is config, not code.
- **The verification ladder is the product.** Every verdict is one row in
  `verifications` carrying `kind` (`human`, `ai_describe`, `ai_tag`,
  `ai_explain`, `ai_verify`, `ai_bulk`), `scope` (`answer`, `explanation`,
  `subtopic`, `media`, `formatting`), `verdict` (`pass`/`fail`/`disagree`/
  `ambiguous`), `verifier` (the model id, or the person), `detail`, and
  `content_hash`. A model verdict must never be able to claim to be human. Only
  a `human` `pass` covering both `answer` and `explanation` counts as verified
  for the API.
- **Catalog is read from production, never written there.** The topic/subtopic
  taxonomy lives in the production database; `catalog` copies it read-only into
  the bank's work lane. AI uses that copy for tagging and explanations.
- **Media goes to our own destination**, content-addressed (sha256 blob names),
  via the media git project. The URL we store is **ours**, never the provider's.
  Upload stays disabled until it is proven with the probe.
- **Deduplication matters.** Two rows with the same stem and options are the
  same question. We do not grow the bank by growing duplicates.
- **AI runs through opencode**, which is already proven in `utmelab-pipeline`.
  We are not re-proving the model backend; we are proving the bank.

### Discipline

- Proven beats claimed. Every "it does X" in a comment or README is a thing to
  demonstrate with a command, on real rows, before we believe it.
- No fake or invented data outside `var/`. No writing production. No touching
  `tools/` or `utmelab-pipeline/`.
- One new planning document is this file. Nothing else gets created.

## The idea, end to end

Acquire from public sources into `raw_`, move into `work_`, clean it with
mechanical gates and dedupe, enrich it with a model (figure descriptions, an
explanation, a subtopic tag, an underline), have the model judge it, let a human
settle only what is left, and mark the survivors `ready_`. Every step is a task
that can run alone and be proven alone. The database, not a JSON file, is the
record.

The flows we want to be able to run, in any order, in any combination:

- **Fill first.** `scrape` + `intake` + `gate` + `dedupe`, no model, no cost.
- **Fetch and judge now.** The fill flow plus `ai-tag`, `ai-explain`,
  `ai-verify` in the same pass.
- **Fill the gaps.** `--where 'no explanation'` then explain only those; or
  `--where 'no subtopic'` then tag only those.
- **Media.** `has images` -> `media-discover` -> `media-fetch` -> (transform) ->
  upload to our store.
- **Compose.** One `goal` that wires these into a full pass.

## What actually exists today

Truth table. "Registered" means the CLI can invoke it now. "Proven" means it has
run on real rows end to end.

| Area | Code | In CLI | Unit-tested | Proven on real data |
|---|---|---|---|---|
| config / env | yes | `config` | yes | **no** (single URL today, see below) |
| contract: rust schema, vocab | yes | `contract` | yes | yes |
| content hash | yes | (inside `contract`) | yes | **yes: 2243/2243 vs live prod** |
| store: lanes, selectors, repo | yes | `selectors` | yes | yes (local) |
| source: myschool | yes | `sources`, `scrape` | partial (`run.py` 15%) | **no** |
| source: jambsyllabus / waecsyllabus | yes | `sources` | partial | **no** |
| catalog (read prod, write bank) | yes | `catalog` | yes | partial (583 / 2158 rows) |
| intake (raw to work) | yes | `intake` | yes | partial (5 rows) |
| gate (mechanical) | yes | `gate` | yes | partial (5 rows) |
| dedupe | yes | `dedupe` | **23%** | **no** (has never refused a row) |
| ai-describe | yes | `ai-describe` | yes | **no** |
| ai-explain | yes | `ai-explain` | yes | **no** |
| ai-tag | yes | `ai-tag` | yes | **no** |
| ai-verify | yes | `ai-verify` | yes | **no** |
| media-discover | yes | `media-discover` | partial | **no** |
| media-fetch | yes | `media-fetch` | partial | **no** |
| media-transform / upload / report / gc | **not built** | no | no | no |
| promote (work to ready) | yes | `promote` | yes | **no** (all `ready_*` empty) |
| review workbench | partial (`set`, `show`, `verify`) | not registered | yes | **no** |
| goal composition | yes | `goal` | partial | **no** |
| status / progress report | **not built** | no | no | no |
| two-DB env wiring (`.env`) | **not built** | no | no | no |

Known doc drift: the README's "Status" section still calls `intake`, the media
tasks, the model tasks, the review bench and `goal` unbuilt. They are built.
Reconcile it when we next touch the README.

## The one dangerous thing, fix before it runs

The bank uses `UTMELAB_BANK_DATABASE_URL` for two different jobs:

- `catalog` treats it as **production**, and reads the authoritative `topics` /
  `subtopics` from it.
- Every other command treats it as **the bank's own store** (`require_database()`
  falls back to it whenever `--local-database` is absent).

So the only currently-safe setup is: that URL points at production, and every
workflow command is hand-passed a local `--local-database`. Nothing enforces it.
One forgotten flag makes a workflow open **production** as its working store and
write `raw_` / `work_` / `ready_` lane tables into it.

Evidence that it has not happened yet: production currently has 23 tables and
**zero** lane tables. The isolation is a habit, not a guarantee.

The fix: two settings, not one. A bank-own URL and token, and a production
**read** URL and token opened with `read_only=True`. Then isolation is
structural.

## Environment and secrets

The `.env` in `utmelab-bank/` (gitignored, confirmed) already carries the two
databases and the media credential. The intended mapping:

| Setting | Env name in `.env` | Used for |
|---|---|---|
| bank own DB url | `TURSO_UTMELAB_BANK_DB_URL` | every lane read/write |
| bank own DB token | `TURSO_UTMELAB_BANK_DB_TOKEN` | every lane read/write |
| production read url | `TURSO_DB_URL` | `catalog`, read-only joins |
| production read token | `TURSO_DB_TOKEN` (prefer a read-only one) | `catalog` |
| media push token | `GITLAB_FINE_GRAINED_ACCESS_TOKEN` | media upload |
| media remote | `UTMELAB_BANK_MEDIA_REMOTE` | media clone origin |
| model | `UTMELAB_BANK_AI_MODEL` | opencode model id |

For local runs the `.env` is read from `utmelab-bank/.env`. On GitHub Actions
the same names come from repository secrets, so the code path is identical and
`.env` is simply absent. Production tokens read-only; the bank holds no write
credential for production.

## Roadmap

Each step ships on its own and is green on its own. We do not start a step until
the previous one is green.

- **R1. Split the two databases and load `.env`.**
  Config gets `bank` (own) and `prod_read` (read-only) connections sourced from
  the names above; `.env` is loaded when present and never overrides real env.
  *Green:* `config` shows both, `catalog` reads production and writes the bank
  DB, and production still has zero lane tables.
- **R2. `status` command.**
  Lane counts, the last N runs with outcome, the retry queue, and how many rows
  are eligible for each flow.
  *Green:* one command answers "are we progressing".
- **R3. CI: a `bank` job.**
  `ruff format --check`, `ruff check`, `mypy`, `pytest`, on push and pull
  request, alongside the Rust gate.
  *Green:* the job is green on GitHub.
- **R4. Prove dedupe.**
  Feed it a real cross-source duplicate and a same-source whitespace variant.
  *Green:* the duplicate is refused and the reason is recorded.
- **R5. Prove the scraper on one subject.**
  `scrape` one subject/year, then re-scrape.
  *Green:* raw rows land, and the second scrape adds zero new raw rows.
- **R6. Prove the AI flow on a small slice.**
  `ai-tag`, `ai-explain`, `ai-verify` over, say, 20 work rows.
  *Green:* verification rows are written with the exact vocabulary production
  joins on, and the run is resumable.
- **R7. Prove media.**
  `media-discover` and `media-fetch` on rows with images; build the upload and
  the report; push one batch to the media project.
  *Green:* blobs land in the media repo and a `media_url` is set on the row.
- **R8. Compose a `goal`.**
  Wire the proven tasks into one named pass.
  *Green:* the goal runs end to end on a slice without any task calling another.
- **R9. Deploy to GitHub Actions.**
  A manual `workflow_dispatch` workflow with inputs (goal, source, subject,
  limit) that can be run N times.
  *Green:* a manual run fills the bank DB and reports its counts in the summary.
- **R10. Retire the prototypes.**
  After one full green cycle: delete the prototype workflows
  (`auto_tag_questions`, `auto-verify`, `auto-verify-free`, `harvest`,
  `pipeline`) and then the `tools/` and `utmelab-pipeline/` directories.
  *Green:* nothing references them and the bank workflow replaces them.

## How it runs

- **Locally first**, to prove a step. `make check`, then the real command against
  the bank DB.
- **GitHub Actions is the primary runner**, because that is where it will live.
  Manual `workflow_dispatch` with inputs and a "run N times" loop. This mirrors
  the old `harvest` workflow, minus the daily cron that currently fails.
- A host timer/service is a later option, not the first target.

## Open decisions

1. Coverage floor: cover the scraper and the gates up to 80%, or lower the floor
   with a stated reason. Suppressing it is not allowed.
2. Which source is proven first: `myschool` (questions) or the syllabus trees.
3. The review tier: the exact rule for "clean enough to need little review"
   (proposed: gate clean + an `ai_verify` pass + scopes covered).
4. Media transform scope before the first push (originals vs derivatives only).
5. The `bank` DB: confirm a fresh Turso database, distinct from the pipeline DB.

## Appendix: current command surface

```text
utmelab-bank catalog      copy the topic/subtopic catalog from prod into the bank
utmelab-bank scrape       fetch questions into the raw lane
utmelab-bank intake       raw -> work, applying the gate
utmelab-bank task NAME    run one task over the rows a selector picks
utmelab-bank goal         run named tasks in sequence as one goal
utmelab-bank tasks        what every task does and what it fills
utmelab-bank sources      what every source can fetch
utmelab-bank selectors    every --where phrase
utmelab-bank explain      what a --where expression selects, in words
utmelab-bank contract     compare a database against what the API reads
utmelab-bank config       where every setting came from
```
