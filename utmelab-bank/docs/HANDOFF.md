# utmelab-bank handoff

**Date:** 21 October 2026
**Status:** read this before changing anything. It records what was measured, what was built, and what is wrong.

---

## 1. What utmelab-bank is

A **content factory**. It produces exam question bundles for the UTME Lab API to serve.

It is **not** the API. It sits beside `utmelab-api-old/` and `src/` in this repository.

```
utmelab-api/                 the serving API (Rust). Reads production Turso, serves questions.
utmelab-api-old/             the production bank code: schema, writes, the serving predicate.
utmelab-bank/                 THIS. The Python factory. Builds and checks content.
utmelab-bank-failed/         the previous attempt. Read FINDINGS.md; do not copy its code.
utmelab-pipeline/             an earlier parallel attempt. Also do not copy.
tools/                        the pre-bank tooling. Contains the original harvester.
```

### The two databases

| Database | URL | Who owns it | What it holds |
|---|---|---|---|
| **Production** | `turso://utmelab-api-ultimatekristency.aws-eu-west-1.turso.io` | the API | 2,243 questions, the catalog, 2,268 verifications |
| **Bank** | `turso://utmelab-bank-shedrackgodstime08.aws-ap-south-1.turso.io` | us | one table, `staging_items` |

We **read** production. We never write it. The catalog lives there and it is the only authority for topic placement.

---

## 2. Scope

### In scope
- Acquiring questions from a source
- Adapting them to the canonical shape
- Reading the production catalog to tag against
- AI proposals: `tag`, `explain`, `verify_answer`, `describe_image`
- Media: fetch, hash, store, describe
- A staging table in our own Turso database
- The gate, dedupe and the state machine

### Explicitly out of scope, stated by the user
- **Human verification.** Not being built.
- **Promotion from utmelab-bank to the production database.** Not being built.
  Moving a row to production and making the API serve it as `verified` is a separate piece of work.

Everything below about promotion is background, not a task list.

---

## 3. Production reality, measured

Read this section before trusting any number, including ours.

### 3.1 The question count is 2,243, not 68,613

`utmelab-bank-failed/FINDINGS.md` says "68,613 rows". **That is stale.** Measured today against the live database:

| Table | Rows |
|---|---|
| `questions` | **2,243** |
| `verifications` | 2,268 |
| `subtopics` | 2,158 |
| `topics` | 583 |
| `subjects` | 34 |
| `blueprints` | 80 |
| `passages` | 8 |
| `exams` | 4 |
| `novels` / `novel_questions` | 6 / 220 |
| `countries` | 5 |
| `api_keys` | 3 |

There is **no media table and no `media_assets` table**. The only media in production is an image mark with a URL.

### 3.2 `questions` columns, exactly

```
id              TEXT    PRIMARY KEY
exam            TEXT    NOT NULL
subject         TEXT    NOT NULL
year            INTEGER NOT NULL
source          TEXT    NOT NULL
text            TEXT    NOT NULL
inline          TEXT    NOT NULL DEFAULT '[]'
options         TEXT    NOT NULL
answer          TEXT    NOT NULL
subtopic_id     TEXT    NULL
section         TEXT    NULL
passage_id      TEXT    NULL
explanation     TEXT    NULL
marks           REAL    NOT NULL
difficulty      INTEGER NOT NULL
content_hash    TEXT    NOT NULL
text_norm       TEXT    NOT NULL DEFAULT ''
```

**There is no `image` column.** A draft of this doc claimed there was. There is not.

### 3.3 The `text` + `inline` split

The stem is **two columns**, not one object:

```json
text:   "Rationalise the denominator of \\(\\dfrac{6}{\\sqrt{3}}\\)."
inline: [{"start":147,"len":16,"kind":"underline"}]
```

But nested texts keep their own inline:

```json
options:    [{"id":"a","text":{"text":"2","inline":[]}}, ...]
explanation: {"key_point":{"text":"...","inline":[]},
               "body":{"text":"...","inline":[]},
               "trap":null}
```

This is `Question.text: RichText` flattened by serde, while `Choice.text` and `Explanation.*` are plain nested structs. The Rust source is `utmelab-api-old/src/bank/model.rs`; the row reader is `utmelab-api-old/src/bank/turso_store.rs` around line 297.

### 3.4 The mark shape

```json
{"start":147,"len":16,"kind":"underline"}
{"start":37,"len":0,"kind":"image","url":"https://...","position":"below","alt":"optional"}
```

`kind` is a lowercase string, one of `bold`, `italic`, `underline`, `strike`, `subscript`, `superscript`, `image`. Image marks carry `url`, `position` (`above` or `below`) and optional `alt`. The mark is **flat**: the kind's fields sit beside `start` and `len`.

Marks actually present today: `image`, `italic`, `underline`.

### 3.5 The catalog shape

```
subjects  (slug PK, exam, name, is_compulsory, objective_paper_questions)
topics    (slug PK, subject -> subjects.slug, exam, name, order, weight, objectives JSON)
subtopics (slug PK, topic -> topics.slug, name, order, objectives JSON)
exams     (code PK, name, countries JSON, status, has_full_paper,
           subjects_required, duration_minutes, rules JSON)
```

`questions.subtopic_id` holds a **subtopic slug**, for example `surds` or `change-of-bases`. `objectives` is a JSON array of strings.

Topics and subtopics have **no separate id**. The slug is the identity. There is no catalog version column; we compute our own content-addressed version.

### 3.6 The serving predicate

`utmelab-api-old/src/bank/reads.rs`, `where_clause()`. This is what decides `verified`:

```sql
(q.exam <> '')
AND (...subtopic must exist in subtopics, and its topic must be allowed for the country...)
AND (?15 IS NULL OR (?15 = 1) = EXISTS (
  SELECT 1 FROM verifications v
  WHERE v.question_id = q.id
    AND v.kind = 'human'
    AND v.verdict = 'pass'
    AND v.content_hash = q.content_hash
    AND EXISTS (SELECT 1 FROM json_each(v.scope) WHERE value = 'answer')
    AND EXISTS (SELECT 1 FROM json_each(v.scope) WHERE value = 'explanation')
    AND NOT EXISTS (
      SELECT 1 FROM verifications v2
      WHERE v2.question_id = v.question_id AND v2.kind = 'human'
        AND (v2.created_at, v2.id) > (v.created_at, v.id)
        AND EXISTS (SELECT 1 FROM json_each(v2.scope) WHERE value = 'answer')
        AND EXISTS (SELECT 1 FROM json_each(v2.scope) WHERE value = 'explanation'))))
```

Five things to hold onto:

1. `q.exam <> ''`. **A question with an empty exam is never served.** `questions.exam` holds `''`, `JAMB` or `WAEC` today. The empty ones are withheld, not broken.
2. `kind = 'human'`. Every one of the 2,268 verifications is `human`, every verdict is `pass`, every scope is `["answer","explanation"]`.
3. `v.content_hash = q.content_hash`. The **stored column** on the question row, compared to the stored column on the verification row. It is not recomputed at read time.
4. The latest human verification wins. A later human fail voids an earlier pass.
5. The subject and topic must exist, and the topic must be allowed for the requesting country.

### 3.7 The content hash algorithm

`Question::content_fingerprint()` in `utmelab-api-old/src/bank/model.rs`. `write.rs` line 50 calls it and stores the result in `questions.content_hash`.

The parts, in order, joined by `U+001F`:

```
1  stem text
2  for each option:  "<option id>" + U+001E + "<option text>"
3  answer
4  marks of the stem, then marks of each option, each mark encoded as
   "<start>,<len>,<kind>", all joined by "|"
5  explanation key_point text
6  key_point marks joined by "|"
7  explanation body text
8  body marks joined by "|"
9  trap text, or "" when there is no explanation or no trap
10 trap marks joined by "|"
```

A mark is encoded as `<start>,<len>,<kind>`, and an image mark is `image:<url>:<position>:<alt>` with an empty alt when there is none.

The whole thing is sha256 of the parts joined by `U+001F`, hex encoded.

**The fingerprint does not cover the passage text, the media, the section or the difficulty.** That is finding F18 in FINDINGS.md and it is still true.

`text_norm` is simply `stem text .to_lowercase()`.

---

## 4. Where our models do not match production

These are real gaps, not style preferences. Fix them before anything is written to production.

| Ours | Production | The gap |
|---|---|---|
| `Mark.length` | `Inline.len` | different column name |
| `Mark.asset_id`, a sha256 | `InlineKind::Image{url, position, alt}` | ours is a hash, production is a **URL plus a position** |
| `Mark.kind`, an enum | a lowercase string, flat | ours needs an image variant carrying `url` and `position` |
| `Content.stem` is one `RichText` | `text` and `inline` are two columns | production splits the stem |
| `Option.id` is `"A"`, `"B"` | `answer` is `"a"`, `"b"` | production ids are lowercase |
| `content_fingerprint()` in `domain/hashing.py` | `Question::content_fingerprint()` | **different structure. Our hashes will not match production's** |
| no `text_norm` | `questions.text_norm` | we do not produce it |
| `MediaAsset`, `MediaRef` | no media table at all | new ground, nothing to match |
| `CatalogTopic.id` and `.slug` are separate | only `slug` | ours is redundant but harmless |
| `CatalogSnapshot.version` | no version column | ours is computed, fine |

Our `content_fingerprint` was written from the architecture document, not from the production source. It must be replaced with the production algorithm before any hash is compared to a production row.

---

## 5. What has been built

`utmelab-bank/src/utmelab_pipeline/`

```
config.py                       settings, read from utmelab-bank/.env
domain/
  enums.py                      State, Capability, MarkKind, SourceCapability, Verdict, VerificationKind
  models/common.py              every model, defined exactly once
  models/proposals.py           model output: ImageDescription, TagProposal, Explanation, AnswerVerdict
  models/catalog.py             re-export, so there is one CatalogRef class
  capabilities.py               the four capability request and response types
  ports.py                      Source, the four provider ports, CatalogReader, MediaStore, StagingStore, MediaFetcher, MediaValidator
  selector.py                   typed query data
  state.py                      the transition table, the only source of truth
  hashing.py                    canonical json, payload_hash, content_fingerprint  (SEE GAP 4)
adapters/
  sources/fixture/              a source that reads recorded JSON
  providers/mock/               a deterministic provider
  providers/opencode/           the real OpenCode CLI provider
  providers/catalog_prompt.py   prunes the catalog before it goes into a prompt
  providers/tagging.py          TagService and ExplainService, the core validators
  catalog/production.py         reads topics and subtopics from production
  catalog/client.py             the turso_serverless driver
  media/git_store.py            git backed media store, GitLab remote
  media/ingest.py               fetch, validate, store
  media/describe.py             describe the assets
  media/consensus.py            reconcile several describers
  store/schema.py               the one table
  store/staging.py              save, load, transition, list by state
```

`utmelab-bank/tests/`

```
conftest.py                     fixtures
test_models.py                  model validation
test_state_machine.py           transitions, the content hash
test_hashing.py                 canonical json
test_ports.py                   the port contracts
test_selector.py                the selector
test_config.py                  the settings
contract/test_fixture_source.py     the fixture source
contract/test_mock_provider.py      the mock provider
contract/test_opencode_provider.py  the OpenCode provider
contract/test_production_catalog.py the catalog reader
contract/test_tagging_service.py    tag and explain
contract/test_consensus.py          consensus
contract/test_git_media_store.py   the media store
contract/test_staging_store.py      the staging store
live/test_opencode_live.py         a real model call, skipped unless UTMELAB_LIVE=1
```

**125 tests pass. mypy strict is clean across `src` and `tests`.**

---

## 6. The environment

### Credentials

`utmelab-bank/.env` is the only file that holds the answers. `utmelab-bank/.env.example` documents every variable.

```
TURSO_PROD_DATABASE_URL     production catalog, read only
TURSO_PROD_AUTH_TOKEN       read only token
TURSO_BANK_DATABASE_URL     our own database
TURSO_BANK_AUTH_TOKEN       write token
GITLAB_TOKEN                for pushing the media repository
NVIDIA_API_KEY              for the Nvidia models
```

Real environment variables always win over the file. The parent repository's `.env` is **not** read.

### The driver

`turso_serverless`, because that is the driver that matches the Turso engine. `pyturso` is source-only and needs a Rust build on aarch64-android. `libsql-client` is for libSQL databases, not Turso ones.

The driver is synchronous, so it is driven from one worker thread, which keeps its thread affinity. A dropped connection is retried, because a flaky network is not a failed run. The network here drops connections often; that is the environment, not the code.

### The catalogue is fetched, never derived

```python
reader = ProductionCatalogReader(client)
snapshot = await reader.snapshot("JAMB", "biology")   # 23 topics, 83 subtopics
```

The version is `sha256:<16 hex>` over the whole tree, computed by us. Production has no version column.

---

## 7. What is not built

- The **gate**. The mechanical check that a question is complete and sane.
- **Dedupe**. Production has `text_norm` for this. We have `payload_hash`.
- **`verify_answer`** wired to a task. The provider method exists.
- **`describe_image`** wired to a task. The provider method exists, the media store exists.
- **Paper assembly.** `blueprints` holds 80 rows for it. Out of scope for now.
- **The CLI.** There is none. Everything is driven from Python.
- **A second source.** The fixture source is a placeholder for the real one.
- **A second provider.** OpenCode is the only real one.

---

## 8. Open decisions

These are not mine to make.

1. **The trust policy.** Production only counts `human` passes. If AI verification is ever to count, that is an API contract change, not a bank change. Until then, AI rows are signal.
2. **The mark shape.** Our `Mark` must change to `len` plus a URL and position for images, to match production.
3. **The content hash.** Ours must be replaced with the production algorithm, or nothing we write can ever match a production row.
4. **The option id case.** Production uses lowercase. Ours uses uppercase in the fixtures.
5. **Where media lives.** Production stores no media. The GitLab media repository is new ground, so the URL convention has to be decided: does the image mark carry the GitLab URL, or a CDN URL that points at it?

---

## 9. Traps

Things that cost time. Do not walk into them again.

- **Two classes with one name.** Earlier there were duplicate `CatalogRef`, `Evidence`, `SourceProfile` and even duplicate `Content` inside one file. Pydantic then failed with "Input should be a valid dictionary or instance of X" for a value that plainly was one. Every model is now defined exactly once, in `models/common.py` or `models/proposals.py`. Keep it that way.
- **A forward reference that resolves to the wrong class.** `Evidence.verifications` was typed `"VerificationRecord"` and Pydantic resolved it to the `Verification` in `validation.py`. The fix was to delete the duplicate and merge the two classes, keeping the trust rules.
- **`model_copy` does not validate.** It is the fastest way to put a bad value into a model. Use `model_validate` when a validator must run.
- **A state that is free text.** `StagingItem.state` was a string and any string passed. It is now the `State` enum, and `transition_to` refuses an invented move.
- **`is` on enum values.** `transition_to` compared with `is` and stored the raw argument, so a string target landed as a plain `str`. It now coerces to `State` first.
- **The provider's error events.** The OpenCode CLI reports failures as `{"type":"error"}` lines. An adapter that only looks for `text` swallows them and reports "no text events".
- **The prompt was 17 KB.** The full catalog with every objective does not fit a sensible prompt. The catalog is pruned now: every id and name goes through, objectives only for candidates matched by keyword overlap.
- **The free tier ran out.** `opencode/deepseek-v4.1-flash-free` stopped answering. `opencode/nemotron-3-ultra-free` still works.
- **The `rebuild` helper had a `print` in it.** It is a test utility. It lives in `models/__init__.py` and it prints nothing.

---

## 10. Running it

```bash
cd utmelab-bank

python -m pytest tests/ -q          # the fast suite
mypy src tests                        # strict, must be clean

UTMELAB_LIVE=1 python -m pytest tests/live/ -q   # a real model call
```

Read the catalog from production:

```python
from utmelab_pipeline.config import load_settings
from utmelab_pipeline.adapters.catalog import catalog_reader

snapshot = await catalog_reader(load_settings()).snapshot("JAMB", "biology")
```

Write a staging row:

```python
from utmelab_pipeline.adapters.catalog import bank_client
from utmelab_pipeline.adapters.store import StagingStore

client = bank_client(load_settings())
store = StagingStore(client)
await store.prepare()          # creates staging_items if it is missing
await store.save(item)
moved = await store.transition(item.id, "catalogued", "enriched")
```

---

## 11. Where the doctrine comes from

- `utmelab-bank/docs/ARCHITECTURE.md` - the architecture this code implements.
- `utmelab-bank-failed/FINDINGS.md` - the evidence file. **Read it, but check every number against the live database.** Its row counts are stale.
- `utmelab-api-old/docs/QUESTION_BANK_DECISIONS.md` - the decision log. D45, D60, D61, D62, D16, D21.
- `utmelab-api-old/docs/RICH_TEXT_HANDOFF.md` - why one `RichText` type exists.
- `utmelab-api-old/docs/UNDERLINE_PROBLEM.md` - why the underline mark matters.
- `utmelab-api-old/docs/CLOZE_PROBLEM.md` - why a missing passage makes a question unanswerable.
- `utmelab-api-old/src/bank/model.rs` - the real types. The source of truth for the schema.
- `utmelab-api-old/src/bank/reads.rs` - the real serving predicate.
