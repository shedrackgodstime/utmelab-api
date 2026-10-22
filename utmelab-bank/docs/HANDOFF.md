# utmelab-bank handoff

**Date:** 21 October 2026
**For:** whoever picks this up next, in a more capable environment.

Read this first. It says what the bank is, what is built, what is measured,
what is wrong, and what to do next. `DESIGN.md` has the reasoning and
`DECISIONS.md` has the sealed decisions, both linked from here.

**State at the end of this session:** 288 tests pass, 12 live tests are
skipped by default, mypy strict is clean across 87 files, and ruff is clean.

---

## 1. What this is

**utmelab-bank is a content factory.** It takes exam content in, decides
whether it is sound, enriches it, checks it, and hands over a bundle that is
complete enough that placing it is a mechanical step.

It is not the API. It is not the server. It does not place content in the
served tables, and it does not build the Rust.

**Where it sits:**

```
sources                utmelab-bank                Turso remote          the API
───────                ────────────                ────────────          ───────
harvest ─┐
syllabus ─┼─▶ intake ─▶ gates ─▶ review ─▶ ready ─▶ bank tables ──sync──▶ replica ──▶ responses
inbox   ─┘                  │         │                           │
                            │         └─▶ live ──▶ reported ──▶ back to intake
                            └─▶ refused, counted
```

**Four jobs, and they are the production doctrine's own words.** From
`docs/NOTES.temp.md` in the parent repository:

> `import`, `quarantine` and `verify` are pipeline work (`utmelab-bank`'s
> intake, promote, gates and review steps), not serving work.

So the bank's four jobs are **intake, gates, review, ready**. Promotion is
not among them, because how a row reaches the served tables is a separate
piece of work that the user has ruled out of scope.

---

## 2. The two documents to read next

| Document | What it is |
|---|---|
| `utmelab-bank/docs/DECISIONS.md` | The sealed decisions, D1 to D13. Where this handoff and that file disagree, that file wins. |
| `utmelab-bank/docs/DESIGN.md` | How the bank is supposed to be, derived from the live production database and the current production source. |

There is a third, older document, `utmelab-bank/docs/ARCHITECTURE.md`. It is
the original brief. It is marked as superseded, and two of its claims are
wrong. Read it for the reasoning, not for the facts.

---

## 3. Production reality, measured

Everything here was measured against the live production database on 21
October 2026. Do not re-measure it, and do not trust the numbers in
`utmelab-bank-failed/FINDINGS.md`, which are stale.

### 3.1 Which source is current

**`src/` at the root of the parent repository is the current production
server.** `utmelab-api-old/` is the archived tree, and the production notes
say so: "The old tree is a source of capabilities, never of structure."

The current server reads the bank tables out of a local synced replica and
never writes them. It does **no semantic validation of a row**: it
deserializes the JSON columns and type-checks the scalars, nothing more. The
server's own test proves what a malformed row does:

```rust
get_question_rejects_bad_option_json  // "malformed options fail loudly"
```

One bad row breaks the endpoint for every consumer, or is served as a wrong
answer. **There is no second line of defence. The gate is the only defence,
and it is the bank's.**

The server is an MVP in progress. Its internals will move. The content shape
is the stable part.

### 3.2 The two halves of the database

| Owner | Tables |
|---|---|
| The server | `meta`, `api_keys`, `dashboard_users`, `sessions`, `reports`. Five, all operational. |
| The pipeline, which is the bank | `questions`, `verifications`, `passages`, `subjects`, `topics`, `subtopics`, `exams`, `exam_requirements`, `countries`, `topic_countries`, `blueprints`, `novels`, `novel_chapters`, `novel_characters`, `novel_themes`, `novel_questions`. Sixteen, all content. |

The handshake is `meta.contract_version`, currently 1, plus `READ_SHAPES`, a
column-level dependency list the server checks on boot and fails closed on.

### 3.3 The numbers

| Table | Rows |
|---|---|
| `questions` | 2,243 |
| `verifications` | 2,268, every one `human`/`pass`/`["answer","explanation"]` |
| `subtopics` | 2,158 |
| `topics` | 583, and only **3** of them carry a weight, so most verified questions sit on unpublished topics |
| `subjects` | 34 |
| `passages` | 8 |
| `blueprints` | 80, and **none** is `measured`: 30 section-level and 19 subject-level are `provisional`, 31 topic-level are `provisional` |
| `novels` / `novel_questions` | 6 / 220 |
| `countries` | 5 |
| `exam_requirements` | 2 |
| `topic_countries` | 0, so the country rule excludes nothing today |
| `reports` | 1 |

**2,189 of 2,243 questions are servable.** The 54 that are not: 50 have no
explanation and so were never verified, 3 have no subtopic, 1 is withheld
with an empty exam.

### 3.4 The content, exactly

A question is 17 columns:

```
id  exam  subject  year  source  text  inline  options  answer
subtopic_id  section  passage_id  explanation  marks  difficulty
content_hash  text_norm
```

- The stem is **two columns**, `text` and `inline`, so the search can use a
  plain one.
- The options and the explanation hold **nested objects** with their own
  `inline`.
- `text_norm` is the **full-Unicode** lowercase. SQLite's `lower()` is ASCII
  only, and 41 live rows prove the difference. Never match on `lower(text)`.
- `content_hash` is the receipt every verification is written against.

The content hash covers the stem, each option's id and text, the answer, the
marks, and the explanation's key point, body and trap. It does **not** cover
the source identity, the catalog reference, the passage text, the media, the
section or the difficulty.

### 3.5 Passages

8 passages, 4 kinds: `Comprehension` (3), `Cloze` (3), `ReadingText` (1),
`Data` (1). 28 questions point at one, and one passage serves up to 9
questions. Every question that points at a passage shares its subject.
Titles repeat, so the id is the only key.

### 3.6 Figures

71 questions carry a figure. It is a **zero length inline** with a url, a
position and an optional alt. Every one is `position: "above"` and every url
points at `myschool.ng`. **There is no media table and no image column
anywhere.** Production stores no bytes, so a figure is one dead host away from
being permanently broken.

The current code says the position is "Data, never inferred". The archived
tree guessed it from the stem's prose, which is how all 71 came to be
`above`. The bank must not guess.

---

## 4. The codebase

```
utmelab-bank/
  pyproject.toml            the package, its deps and its config
  .env                      the credentials, never committed
  .env.example              the shape of it
  var/                      local state, never in the parent directory
  src/utmelab_bank/
    config.py               the settings, one file holds the answers
    domain/                 no I/O, no provider names, no framework imports
      enums.py              the fixed vocabulary
      models/               every model, defined exactly once
        common.py           the canonical values
        catalog.py          the catalog shapes
        proposals.py        what a model proposes
      gate.py               THE GATE. The rules, pure.
      dedupe.py             the two fingerprints
      review.py             the review scope and the check kinds
      audit.py              the agreement measurement, pure
      ready.py              the eight conditions and the report
      reports.py            the report and drift shapes
      hashing.py            the content fingerprint
      state.py              the state machine
      capabilities.py       the capability names and their requests
      ports.py              the interfaces the adapters implement
      selector.py           the selector
    adapters/               each one imports domain and its own library
      database.py           the turso_serverless driver, both databases
      catalog.py            the production catalog reader
      production.py         the production content and report readers
      gate_service.py       runs the gate over a staging item
      dedupe_service.py     runs the dedupe step
      review_service.py     runs the review and records the check
      audit_service.py      samples the machine's work and measures it
      ready_service.py      checks the bundle against the eight conditions
      report_service.py     a complaint becomes work
      drift_service.py      the row that moved under the check
      index_refresh.py      reloads the content index from production
      media/
        git_store.py        the content addressed store
        ingest.py           fetch, validate, store
        describe.py         describe the assets
        consensus.py        reconcile several describers
      providers/
        mock/provider.py    the provider that needs no network
        opencode/provider.py  the provider that runs the model
        catalog_prompt.py   the prompt, with the catalog pruned
        tagging.py          tag and explain, with the core validating
      sources/fixture/      the fixture source
      store/
        schema.py           the bank's tables and their migrations
        staging.py          save, load, transition, list by state
        index.py            the content index
        reports.py          the report log
  tests/
    conftest.py             the fixtures
    test_*.py               the unit tests
    contract/               one suite per source, provider and service
    live/                   the contracts that hit the real database and model
      production_rows.py    the shared row parsing for the live tests
  docs/
    HANDOFF.md              this file
    DESIGN.md               how the bank is supposed to be
    DECISIONS.md            the sealed decisions
    ARCHITECTURE.md         the original brief, superseded in part
```

### 4.1 The state machine

`domain/state.py` is the only source of truth for transitions. `rejected` and
`failed` are terminal. Everything else moves.

```
planned     -> acquired
acquired    -> adapted
adapted     -> gated
gated       -> deduped
deduped     -> catalogued
catalogued  -> media_ready -> described -> enriched
catalogued  -> enriched            (the media step is optional)
enriched    -> verified
verified    -> ready
ready       -> live                (handed over, so the bank tracks it)
live        -> reported            (a consumer complained)
live        -> enriched            (it drifted, so the check is stale)
reported    -> enriched            (the content is reworked)
```

**The pipeline is a loop.** Content that is already in production comes back,
twice over: a report says the content is wrong, drift says the check on it is
stale. Both land back at `enriched`, because both need the content looked at
again before it is checked again.

### 4.2 The gate

`domain/gate.py`, pure, no I/O. The default is fail.

**Every refusal goes to the same person.** The gate refuses, and the person
either fixes the content or records a `Clearance` with a reason. One queue,
one mechanism, and nothing leaves the bank without a person having looked at
it. The severity stays on the issue, so the counts still say what was
objectively broken and what needed judgement.

The rules:

| Rule | Severity | Live rows |
|---|---|---|
| `answer_not_an_option` | defect | 0 |
| `catalog_scope_mismatch` | defect | 0 |
| `cloze_without_passage` | judgement | 9 |
| `duplicate_content` | defect | 0 |
| `duplicate_id` | defect | 0 |
| `duplicate_near` | judgement | 0 |
| `exam_empty` | defect | 1 |
| `explanation_missing` | defect | 50 |
| `html_in_text` | defect | 0 |
| `image_inline_not_anchor` | defect | 0 |
| `image_url_not_https` | defect | 0 |
| `inline_out_of_bounds` | defect | 0 |
| `inline_partial_overlap` | defect | 0 |
| `marks_out_of_range` | defect | 0 |
| `missing_figure` | judgement | 2 |
| `novel_leak` | judgement | 0 |
| `option_count` | defect | 11 |
| `option_id_duplicate` | defect | 0 |
| `option_id_not_known` | defect | 0 |
| `option_text_empty` | defect | 0 |
| `passage_id_mismatch` | defect | 0 |
| `passage_not_found` | defect | 0 |
| `passage_subject_mismatch` | defect | 0 |
| `placement_scope_mismatch` | defect | 0 |
| `stem_empty` | defect | 0 |
| `subtopic_not_in_catalog` | defect | 0 |
| `subtopic_topic_mismatch` | defect | 0 |
| `subtopic_topic_missing` | defect | 0 |
| `underline_missing` | judgement | 0 |
| `year_out_of_range` | defect | 0 |

**Measured against the live bank: 2,178 of 2,243 rows pass.** The 65 that do
not are exactly the rows that cannot be reviewed into service.

The figure rule fires on the word "table" in a stress question. That is the
live behaviour and it is right, because a rule that guessed would let a real
missing figure through. It is a judgement, so a person clears it in seconds.

### 4.3 The eight conditions of a ready bundle

`domain/ready.py` and `adapters/ready_service.py`. Each is one function that
says why a row does not meet it.

`gated`, `reviewed`, `placed`, `complete`, `explanatory`, `resolvable`,
`identified`, `new`.

**The human sign-off is not one of the eight**, because the bank cannot give
it. Only a person can, and the server's predicate counts only a person. So
the report counts how many rows carry a human pass and leaves the decision
alone.

**Measured against the live bank:**

| Condition | Met | Unmet | Why |
|---|---|---|---|
| gated | 2,242 | 0 | |
| reviewed | 2,192 | 50 | no check covers the answer and the explanation |
| placed | 2,240 | 2 | there is no placement |
| complete | 2,242 | 0 | |
| explanatory | 2,192 | 50 | there is no explanation |
| resolvable | 2,242 | 0 | |
| identified | 2,242 | 0 | |
| new | 2,242 | 0 | |

**The live bank's only shortfall is the 50 rows with no explanation.**

### 4.4 The bank's own tables

| Table | What it holds |
|---|---|
| `staging_items` | One row per item in flight. The content, the placement, the media, the evidence, the hashes, the state. |
| `passages` | The stimuli content refers to, keyed by id so two questions share one row. |
| `content_index` | Both fingerprints of every question the bank knows, so a duplicate check is a lookup. |
| `report_log` | The reports the bank has already acted on, so a complaint does not open the same work twice. |

Seven indexes. The schema is created and migrated by `ensure_schema`, which
adds a column if the table is older than the code. SQLite has no "add column
if not exists", so `schema.MIGRATIONS` names the column and the statement and
`ensure_schema` checks the column list first.

---

## 5. What is built, and what is not

### 5.1 Built and verified

| Piece | Where | Verified by |
|---|---|---|
| The gate | `domain/gate.py`, `adapters/gate_service.py` | 44 unit tests and a live contract test over all 2,243 live rows |
| The passage as its own object | `domain/models/common.py`, `store/` | 6 tests, and a live round trip against the bank database |
| One vocabulary | everywhere | the fingerprint live test, byte for byte against production |
| Dedupe | `domain/dedupe.py`, `adapters/dedupe_service.py`, `store/index.py` | 22 tests, and a live test that feeds a production row back in and watches it get refused |
| The review | `adapters/review_service.py` | 17 tests, and a live test against the real model |
| The audit | `domain/audit.py`, `adapters/audit_service.py` | 8 tests |
| The ready bundle | `domain/ready.py`, `adapters/ready_service.py` | 15 tests, and a live test that builds a bundle from the live bank |
| Reports and drift | `domain/reports.py`, `adapters/report_service.py`, `adapters/drift_service.py` | 12 tests, and a live test against the real reports and hashes |
| The commit contract | `adapters/database.py` | 19 tests |

### 5.2 Not built

- **A real source.** The fixture source is a placeholder. The production
  tools show the range: harvested pages, syllabus files, an inbox of claims,
  passages recovered from papers. The `SourceCapability` enum already names
  them.
- **The media pipeline is half built.** The store, the ingest, the describe
  and the consensus exist. The upload does not, so figures still point at
  `myschool.ng`. That is the expected state of a pipeline that has not
  reached that step.
- **The CLI and the task runner.** Everything is driven from Python. The
  architecture brief describes an `application/` layer and an `interface/`
  layer. Neither exists.
- **The placement of a bundle.** The bank stops at ready. That is out of
  scope by the user's decision.
- **The human review surface.** The review step is a service, not a screen.
  The person audits a sample and records the verdict; there is nothing to
  record it in yet.

### 5.3 The open decisions, and who owns them

| Decision | Owner | What the bank does meanwhile |
|---|---|---|
| Does an AI pass count toward servable? | the server's contract | Produces the content, records the AI pass, and ships the human's sample audit as the evidence for the change. |
| Who places a ready bundle, and when? | separate work | Makes the bundle self-describing, mechanically placeable and idempotent. |
| What agreement rate is good enough? | the human | Measures it on a sample and reports it, with the two directions of disagreement counted apart. |

None of them blocks the gate, the dedupe, the review or the ready bundle.

---

## 6. The order to build the rest in

1. **A real source.** The fixture source is the last thing standing between
   the bank and real content. Start with the syllabus, because the catalog
   is what everything is placed against, and 3 of 583 topics carry a weight
   today.
2. **The media pipeline.** Fetch the figure bytes, hash them, store them,
   describe them, and swap the url at handover. 71 rows now, 71,000 later,
   and the cost of finding out late is proportional to the size of the bank.
3. **The CLI and the task runner,** so the pipeline can be driven by
   something other than a Python shell.
4. **The review queue.** A list of the rows that need a person, and a way to
   record the verdict.
5. **The placement of a bundle,** if it is ever brought back in.

---

## 7. How to run it

```bash
cd utmelab-bank

python -m pytest tests/ -q          # the fast suite, about 3 seconds
mypy src tests                       # strict, must be clean
ruff check src tests                 # must report nothing
ruff format --check src tests        # must report nothing

UTMELAB_LIVE=1 python -m pytest tests/live/ -q   # the real database and the
                                                # real model, about 6 minutes
```

`ruff` and `mypy` are declared in the dev extras and configured in
`pyproject.toml`. Both must be clean.

### 7.1 The live tests, and what they cost

| Test | What it proves | Cost |
|---|---|---|
| `test_production_fingerprint_live.py` | every live row hashes the way we hash it | 1 query, about 5 s |
| `test_gate_live.py` | the gate sees what the live bank shows | 1 query, about 5 s |
| `test_ready_live.py` | the eight conditions describe the live bank | 1 query, about 45 s |
| `test_dedupe_live.py` | the dedupe catches a production row | a full index refresh, about 2 minutes |
| `test_report_live.py` | the reports and the drift check work | about 90 s |
| `test_opencode_live.py` | the provider answers | about 20 s |
| `test_review_live.py` | the review works against the real model | about 60 s |

**The live suite takes about six minutes on a slow link**, because a round
trip to Turso costs about a second. Run the fast suite while you work and
the live suite before you trust a change.

### 7.2 The environment

The package declares its runtime dependencies in `pyproject.toml`:
`pydantic`, `turso-serverless`, `httpx` and `Pillow`. Install the package and
its dev extra once:

```bash
pip install -e ".[dev]"
```

`utmelab-bank/.env` holds the credentials and is never committed. The
variables are `TURSO_PROD_DATABASE_URL`, `TURSO_PROD_AUTH_TOKEN`,
`TURSO_PROD_AUTH_TOKEN_READONLY`, `TURSO_BANK_DATABASE_URL`,
`TURSO_BANK_AUTH_TOKEN`, `GITLAB_TOKEN` and `NVIDIA_API_KEY`. Real
environment variables win over the file.

**Local state belongs in `utmelab-bank/var/`.** Never in the parent
directory.

**The driver is `turso_serverless`.** `pyturso` is source-only and needs a
Rust build, and `libsql-client` targets a different engine. The decision was
settled and tested.

---

## 8. The traps

These cost time. Do not walk into them again.

- **A write that is not committed is a write that did not happen.** The
  driver opens a deferred transaction, so the client has to commit. It did
  not, and every write the bank made was rolled back when the connection
  closed. It looked like it worked, to the connection that made it, and was
  gone by the next one. The symptom was a live check that reported 2,243
  rows and a fresh process that read 0. **Read back from a new connection,
  not the one that wrote.**
- **A round trip is about a second.** Both databases measure 0.7 to 1.4
  seconds per query from where the bank was built. One write per row is an
  hour for a bank of two thousand. The index refresh went from 50 minutes
  unbatched, to 123 seconds with a commit per statement, to 39 seconds with a
  500-row batch and one commit.
- **A model wide strip rewrites content.** `DomainModel` carried
  `str_strip_whitespace=True`, so pydantic trimmed every string on every
  model. Two production rows have a leading space in the explanation, and
  trimming it changed the fingerprint, so those two rows could never match
  production. **A sample of 394 rows missed it, because those two rows were
  not in the sample.** Check against everything, not a slice.
- **A url type that normalises.** `HttpUrl("https://example.com")` is
  `https://example.com/`. The url is hashed, so normalising it silently
  changes the row. Anything that is hashed must be stored verbatim.
- **"Must not overlap" is not the rule.** Two inlines may share an identical
  range, and the decision log names the case, bold on top of underline.
  Production refuses only *partial* overlap.
- **SQLite's `lower()` is ASCII only.** 41 live rows have a `text_norm` that
  SQLite's `lower(text)` would never produce. Python's `.lower()` and Rust's
  `.to_lowercase()` are full-Unicode and do produce it.
- **The archived tree is not the current source.** `src/` at the root of the
  parent repository is the current server. The archived tree's import rules
  and the live tooling's rules are **different**, and the live ones are in
  force.
- **The live gate flags, it does not refuse the row.** `tools/review.py`
  refuses to *verify* a quarantined row, which is different from refusing the
  row. The figure hint words collide with ordinary English, so "table" in a
  stress question is not a missing figure.
- **The staging id is not the production id.** The staging id is
  `source:source_item_id`, so two sources cannot collide. Production keys
  its rows by the bare id. The drift check looks up by
  `provenance.source_item_id`, and it got this wrong at first.
- **`model_copy` does not validate.** It is the fastest way to put a bad
  value into a model. Use `model_validate` when a validator must run.
- **Two classes with one name.** There were duplicate `CatalogRef`,
  `Evidence`, `SourceProfile` and even duplicate `Content` in one file, and
  pydantic then failed with "Input should be a valid dictionary or instance
  of X" for a value that plainly was one. Every model is now defined exactly
  once.
- **A bulk rename is not a rename.** Renaming `marks` to `inline` also
  renamed `Content.marks`, which is the mark *value*, and
  `SourceCapabilities.marks`, and the payload key `marks`. The mark value
  keeps the word marks, because production has a `marks` column and an
  `inline` column and so do we.
- **`ruff` is configured but not installed.** The config existed with ruff
  undeclared. It is declared now, and pyflakes is what runs here.

---

## 9. The live contract tests, which are the real safety net

Twelve tests hit the real database or the real model. They are the proof
that the bank agrees with production, and they should be run before any
change is trusted.

- The fingerprint matches production on **all 2,243 rows**.
- The gate sees the live bank's defects and nothing else.
- The eight conditions describe the live bank, and its only shortfall is the
  50 rows with no explanation.
- A production row fed back into the dedupe is refused as `duplicate_exact`.
- The reports are read once and acted on once.
- The drift check compares against the hashes production holds.
- The review works against the real model.

**A new rule, a new condition or a change to the fingerprint needs a live
test.** That is the pattern the whole session followed, and it is what caught
the whitespace bug and the commit bug.

---

## 10. One paragraph for the person who picks this up

The bank is a content factory whose output is a bundle of exam questions that
are complete, correct, placed, identified and reviewed, so that placing them
is a mechanical step. It is not the API and it does not place anything. The
server does no validation of content, so the bank's gate is the only quality
control the content ever gets, and it is strict: the default is fail, and
every refusal goes to a person who either fixes the content or records a
reason. The content shape is production's, word for word, because the live
tooling writes against that shape and the fingerprint has to match byte for
byte or no row can ever be served. The human is on the critical path for the
refusals and for a sample of the passes, and the number that decides how much
content can move is the agreement rate between the two, which has not been
measured on a real run yet. That measurement is the first thing worth doing.
