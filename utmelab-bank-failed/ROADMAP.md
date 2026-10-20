# utmelab-bank ROADMAP

The plan of record. `README.md` is the design reference. This file is the
status truth. When they disagree about status, this file wins.

## Objective

Turn public exam questions into production-ready rows: acquire, gate, dedupe,
enrich, verify, mark ready. The bank stops at ready. It never serves, never
writes production, and never owns the syllabus.

## Scope

Three layers:

- `utmelab-api` serves verified content. It is read-only. It never crawls and
  never runs AI.
- Production Turso is the source of truth for reference data and for content
  already served.
- `utmelab-bank` is the content factory.

### Ownership

| Data | Owner | Bank |
|---|---|---|
| exams, subjects, topics, subtopics, blueprints, requirements | production | read |
| questions, passages, media, verifications | bank | write |
| runs, outcomes, scrape targets | bank | local |

Anything not on this list is out of scope.

### Boundaries

- The bank has its own database. It never writes production.
- Moving ready rows into production is out of scope.
- The final human check before serving is out of scope.
- `tools/` and `utmelab-pipeline/` are reference only. Never edit them.
- Syllabus and taxonomy are read from production. Never scraped, copied, or
  invented.
- Passages are content. A question that points at a stimulus must carry it.

## Shape

- Tasks are independent. Each runs alone. Composition is a `goal`, written last.
- Selectors are the glue: `no explanation`, `no subtopic`, `unverified`,
  `has images`, `run=N`, `id=...`.
- Sources and AI providers are plugins.
- The verification ladder is the product. A model verdict can never claim to be
  human. Only a human `pass` on answer and explanation counts as verified.
- Media has two outcomes, and both leave a working url. An unuploaded figure
  keeps the provider url. An uploaded figure carries our bare file name.
- Dedupe checks the bank lane and the production content hashes.
- AI runs through opencode. The model is config, not code.

## Data

Content tables: `questions`, `passages`, `media`, `verifications`, plus `runs`,
`run_outcomes`, `scrape_targets`.

Reference is not stored. `store/reference.py` reads production read-only:
topics and subtopics by `(subject, exam)`, a subject, and the content hashes
already served. Cache per run.

Passages are content, not reference. A stimulus comes from the detail page, so
the `html` strategy carries passages; the `api` listing does not. Acquisition
writes the passage to the raw lane and links the question. Intake copies it to
work under the same id. Tagging, explaining, verifying, and review read it from
the bank lane.

`questions` and `media` keep lane prefixes. `passages` and `verifications` still
carry unused lane copies; R15 removes them. The bank has no `subjects`, `topics`,
or `subtopics` tables.

## Current state

Proven on real rows:

- media upload to GitLab, including protected-branch fallback and bare names
- content hash parity: 2243/2243 against production
- scraper, intake, gate, dedupe, fill planner
- ai-describe, ai-explain, ai-tag, ai-verify
- media discover, fetch, verify
- goal `media`
- split ingest and enrich workflows

Known gaps:

- `passages` and `verifications` keep lane copies the data does not need.
- `ready_media` is never written; the API has no media read shape.
- 15 tables where the data needs 7.
- `content_hash` covers the question, not its passage, and cannot change
  without breaking the API join. The bank now requires the `passage` scope on a
  pass, so its own view re-opens when a stimulus is edited. Production's
  `verified_predicate` ignores that scope, so an edit after promotion is not
  voided there.

## Roadmap

Done: R1 to R14. Two databases, status, CI, dedupe, scraper, AI, media, goals,
the split runners, the reference reader, and the passage path.

Next, green on its own:

- **R15. Collapse the lanes.** One `verifications` table, no unused lane copies,
  and updated selectors, promotion, status, and tests.
  *Green:* the full suite is green and `status` reports the same counts on a
  fresh database.

## Environment

| Setting | Env | Used for |
|---|---|---|
| bank url | `TURSO_UTMELAB_BANK_DB_URL` | lane reads and writes |
| bank token | `TURSO_UTMELAB_BANK_DB_TOKEN` | lane reads and writes |
| production read url | `TURSO_DB_URL` | `reference` |
| production read token | `TURSO_DB_TOKEN_READONLY` | `reference` |
| media push token | `GITLAB_ACCESS_TOKEN` | media upload |
| media remote | `UTMELAB_BANK_MEDIA_REMOTE` | media clone |
| model | `UTMELAB_BANK_AI_MODEL` | opencode |

Production is opened read-only with a read-only credential. A missing
credential fails the task. It never falls back to the bank url.

## Open decisions

1. The review tier rule: gate clean, an `ai_verify` pass, and the scopes covered.
2. Media transform scope before the first push.

## Commands

```text
utmelab-bank scrape       fetch one exam/subject/year into the raw lane
utmelab-bank fill         walk the scrape plan
utmelab-bank intake       raw -> work, applying the gate
utmelab-bank task NAME    run one task over a selector
utmelab-bank goal NAME    run named tasks in sequence
utmelab-bank status       lane counts, queues, recent runs
utmelab-bank tasks        task catalogue
utmelab-bank sources      source catalogue
utmelab-bank selectors    selector vocabulary
utmelab-bank contract     compare a database against the API contract
utmelab-bank config       where settings came from
```
