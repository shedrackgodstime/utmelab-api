# utmelab-bank

The bank's supply side. Everything a candidate sees in the product got here
through this package: it acquires questions from public sources, gates them,
asks a model to describe, tag and verify them, lets a human settle what is left,
and marks the survivors ready for production.

## Why it exists

Two earlier attempts proved the same idea twice, and both are kept as reference
only. Neither is maintained, neither is to be touched, and both are read for
ideas rather than for code.

- `tools/` proved the steps work, writing to JSON files committed to the repo.
- `utmelab-pipeline/` proved the same steps work, writing to its own Turso
  database, after JSON turned out to be a bad substrate.

This is the third attempt, built once, with four differences that matter.

1. Staging is its own set of tables inside the bank database. A bad run damages
   staged rows and nothing else.
2. The database is the single source of truth. Nothing here writes a JSON file
   into the repository.
3. Each step runs on its own. Scrape without gating. Gate without spending a
   token. Describe an image without writing an explanation.
4. The order is not fixed yet. Steps are independent units and the orchestration
   is written last, once every unit is proven alone.

The JSON sink survives as a development convenience behind `--sink json`, and it
only ever writes under `var/`, which the repository already ignores.

## Scope

This package writes the bank database and nothing else. It never writes the
production tables the API reads. Moving ready rows into the production database
is a future task, deliberately out of scope for now.

`src/store/schema.rs` belongs to the API. It is read here and never edited.

- `contract/rust_schema.py` parses `CONTRACT_VERSION` and `READ_SHAPES` out of
  it as text.
- `contract/version.py` refuses to act when the database carries a contract
  version this package does not implement.
- `contract/check.py` probes the live database against `READ_SHAPES`, the same
  way the API does on boot.
- `contract/content_hash.py` owns the one content hash. The API never recomputes
  it, it reads the column and joins on it, so a wrong hash from here is silently
  wrong for the reader. That is our responsibility alone.

## Lanes

Three lanes, one per lifecycle stage, as tables rather than a status column.

```
raw_questions     what the source said.   append only, never updated.
raw_media         distinct figure urls discovered.

work_questions    what we believe.        mutable. where every task works.
work_media
work_passages
work_subjects / work_topics / work_subtopics

ready_questions   fully verified, ready for production.
ready_media / ready_passages / ready_subjects / ready_topics / ready_subtopics
```

Lanes are tables, not a status flag, so that a task with a wrong `where` clause
cannot reach a verified row. `ai-explain --where 'no explanation'` addresses a
table it cannot damage.

A table gets a `raw_` lane only when the source payload must be preserved
verbatim. Questions and media qualify, because scrapers drift and re-parsing
should not require re-scraping. Catalog does not, because a syllabus page is
cheap to refetch and deterministic to reparse.

`scrape` writes `raw_` only. A separate free task moves raw into work:

```bash
utmelab-bank scrape --source myschool --exam jamb --subject physics --year 2025
utmelab-bank intake --where 'raw only'
```

Dedupe on `raw_questions` is unique on `(source_url, source_item_id,
payload_hash)`. Re-scraping an unchanged paper adds nothing. A question the site
silently edited appears as a new raw row beside the old one rather than
overwriting it, which makes upstream drift a fact we can see.

## Catalog

The topic/subtopic taxonomy is not scraped from syllabus sites. It is stored in
the production database, the same source the pipeline reads, and it is the single
source of truth `ai-tag` uses to pick a `subtopic_id`. `catalog` copies it into
the bank's work lane read-only, keyed by the production slugs, so a second run
changes nothing:

```bash
utmelab-bank catalog --target work   # reads production, writes var/bank.db
```

It reads `topics` and `subtopics` from the production database (set
`UTMELAB_BANK_DATABASE_URL` / `UTMELAB_BANK_DATABASE_TOKEN`) and upserts the
rows into `work_topics` / `work_subtopics`. After this, `ai-tag` can resolve a
question's subject and exam against the taxonomy.

## Tasks

The unit of work is a task, not a capability, because capability is worth
keeping for later. Each task is runnable alone with nothing else required.

```
gate_mechanical   fills work_questions.gate_status          no tokens
dedupe            fills work_questions.fingerprint           no tokens
media_fetch       fills work_media.blob_path                network
media_transform   fills work_media.derived_path             local
media_upload      fills work_media.media_url                git
ai_describe       fills work_media.description              model, image input
ai_explain        fills work_questions.explanation           model, needs a description
ai_tag            fills work_questions.subtopic_id           model
ai_underline      fills work_questions.inline                model
ai_verify         fills work_verifications                   model
review            human, settles what the model would not
intake           raw_* -> work_*
promote           work_*  -> ready_*
```

Each task declares four things, and that is the entire interface.

```python
class Task(Protocol):
    name: str
    requires: tuple[str, ...]      # tasks whose output it consumes
    produces: str                   # the field it fills
    may_write_ready: bool = False   # true only for promote
```

A task does not know where rows come from, so the caller chooses:

```bash
--where 'run=42'                      just acquired
--where 'has images and no description'
--where 'no subtopic'
--where 'id=q_1183,q_1184'
--target raw | work | ready
```

Every task carries its own named selectors, so `--where 'no description'` means
one thing for `ai_describe` and another for `ai_tag`. Selectors are data, so a
new one can be added without touching the task.

A task that needs an unmet requirement refuses those rows and names what is
missing. It does not quietly chain.

```bash
utmelab-bank ai-explain --where 'no explanation'
# 187 rows explained
# 13 rows skipped: ai_describe has not run for these
```

Chaining is written later, as a named sequence over tasks that already work
alone. No task gains the ability to call another.

## Errors

One run row per execution: task, target, selector, start, finish, succeeded,
skipped, failed. Per row: `attempts`, `status`, `error`, `next_retry_at`.

```bash
--on-error stop | skip | retry      default retry, with backoff and a cap
```

One dead image url does not end a 200 row fetch. The process exit code still
reports that something failed, so a workflow notices. Failures accumulate as
rows to retry, which is why `--where 'attempts < 3'` is a selector like any
other.

## Media store

The store is a clone of the media project. There is no second copy and no blob
interface, because with git as the target a separate store would only duplicate
every byte.

```
utmelab-bank/var/media-repo/           clone of the media project
  media/ab/abcdef0123....png       the blob, named by its sha256, never moves
  manifest/jamb-physics-2025.json  which figures that paper used
```

`media_fetch` writes into the clone. `media_transform` writes derivatives into
the clone. `media_upload` is `git add`, one commit, one push. `media_gc` is
`git clean` scoped to blobs no work row references. The working tree doubles as
the pending batch, so a run that dies before pushing leaves its work where the
next run finds it.

Content addressing and git agree: a blob already in history is never re-sent, so
a batch of 400 figures where 380 already exist costs almost nothing.

**The media url stored in the bank is ours, not the provider's.** A verified
figure's question carries `/media/ab/abcd....png`, never a gitlab url. A figure
whose description failed the check keeps the provider's full url, so the bank
never publishes a copy it cannot explain. The project that serves our copy is a
configuration detail, so moving off git later is a config change and not a data
migration. The same reasoning applies to every other outbound url.

Because the project is private, raw urls are not readable without a credential.
The API serves the media and keeps the token server-side. The bank never holds
a credential.

## Media project

Private. Size and speed matter more than history, so the plan is one commit,
amended in place and force pushed. Clones stay one commit deep and the tree is
the whole cost.

Safety does not come from history. It comes from these rules:

- Always clone or fast-forward from the remote before amending, so nothing
  remote is discarded unseen.
- The database manifest is the record of what should exist, not git.
  `media-report` diffs the manifest against the tree and reports drift.
- Derivatives are committed, originals are not. The tree stays web sized.
- `media-report` reports repository size, object count, uncommitted blobs, and
  how many work rows still lack a media url.

```bash
utmelab-bank media-report
utmelab-bank media-upload-probe --count 8      # real sizes, real pack, no push
```

`media_upload` will not push unless explicitly enabled, and the probe exercises
everything up to the push. It publishes one batch per pass and amends the
single commit in place. Enabling it needs its own session, not a line in a
config file.

## Layout

```
utmelab-bank/
  pyproject.toml          ruff, mypy, pytest-cov, script: utmelab-bank
  Makefile                check, test, lint, types, contract, tasks
  src/utmelab_bank/
    cli.py                one entry point, over both registries
    config.py             one typed config, environment plus flags
    errors.py             typed errors, each with a code and a retry decision

    contract/             everything that reads the API's schema file
      rust_schema.py      parse CONTRACT_VERSION, READ_SHAPES, and the DDL list
      version.py          versions we implement, refuse the rest
      check.py            probe the live database against READ_SHAPES
      content_hash.py     the one content hash, with pinned vectors
      vocab.py            every closed value set in one file

    model/                pydantic shapes, no IO
      base.py             now_iso, parse_iso, to_row, from_row
      richtext.py         RichText, Mark, Option, mark_key, snap_offsets
      question.py         Question, QUESTION_COLUMNS
      catalog.py          Exam, Subject, Topic, Subtopic
      passage.py         Passage and the passage floor
      media.py           MediaRow, the three-step media inventory
      verification.py    Verification and the values the API joins on
      run.py             Run and RowOutcome, the audit trail

    store/                the only package that contains SQL
      schema.py           lane DDL, indexes, migrations, lane parity
      client.py           turso and local sqlite, plus every shape probe
      repository.py       every read and write, lane parameterised
      selectors.py        the named selector vocabulary
      fingerprint.py      stem_fingerprint, internal only

    sink/                 where rows land, and the guard that stops it
      base.py             the protocol both halves write through
      db.py, json.py      the json sink writes under var/, nowhere else

    source/               plugins: where raw material comes from
      base.py             the Source protocol
      http.py             one polite session, one user agent, one delay
      myschool/           parser.py plus jamb, waec, neco as config
      syllabus/           jambsyllabus, waecsyllabus

    task/                 plugins: what work can be done to a row
      base.py             the Task protocol and the run envelope
      promote.py          the only task that may write the ready lane
      gates/              mechanical, dedupe, media_presence
      media/              fetch, transform, upload, report, gc
      ai/                 runner, prompts, schemas, parse, describe, explain, tag, verify
      review/             the workbench

    text/                 shared text handling, no IO
      slug.py, htmltext.py, richtext.py

    blob/                 the media clone
      gitstore.py, paths.py

  tests/
    conftest.py
    test_architecture.py  the rules, checked rather than trusted
    test_contract.py      the API boundary, against the real schema.rs
    test_store.py         lanes, selectors, repository, the json sink
    test_tasks.py         the gate, text handling, the run envelope
    test_cli.py           the command line, sources, the media store
    vectors/content_hash.json
```

## Reuse, enforced

Tasks may not import tasks. Since a task cannot reach another one, the only way
for two of them to share code is to put it in `model`, `text`, `store` or
`contract`, which means it is written once and found once. The previous Python
had five fingerprints, four copies of a detail parser, three `slugify`
implementations and three `load`/`save` pairs, and nothing stopped the first copy
from being followed by a second.

So `tests/test_architecture.py` checks the rules instead of asking for them:

| Test | Rule |
|---|---|
| `test_no_task_imports_another_task` | tasks do not reach each other |
| `test_only_store_contains_sql` | SQL lives in `store` and nowhere else |
| `test_only_the_json_sink_touches_the_filesystem` | no generated data in the repository |
| `test_no_library_code_prints` | `logging`, not `print` |
| `test_no_bare_except` | no `except Exception: pass` |
| `test_our_question_columns_are_declared` | we only write columns the API reads |
| `test_only_promotion_may_write_the_ready_lane` | one writer for verified rows |
| `test_every_selector_has_a_python_equivalent` | the two sinks speak one vocabulary |

The first three are the rules that would each have caught a real incident in the
code this replaces.

## Ported, not reinvented

`tools/` and `utmelab-api-old/` are the reference. They are not read for ideas
only: where one of them solved a problem, this package ports that solution and
cites it. Re-deriving a solved problem is how a second bug gets written, and
three of the first drafts of this package did exactly that.

Four that mattered, each caught by measuring against the committed bank rather
than by reading the code:

**The content hash.** The algorithm is `Question::content_fingerprint` from
`utmelab-api-old/src/bank/model.rs`, which `tools/review.py` mirrored and which
`utmelab-pipeline`'s promoter claimed byte-for-byte parity with. The first draft
here put the stem marks in their own part and glued each option's marks onto its
own option part. That is a perfectly reasonable-looking algorithm which produces
a different digest for **every question in the bank**. Measured: 0 of 2190
stored hashes matched. Now 2171 match and the remaining 19 differ from the
reference in exactly the same way, so the parity is exact and those 19 are a
pre-existing property of the committed data.

The vectors in `tests/vectors/content_hash.json` are digests **read out of**
`utmelab-api-old/data/verifications.json`, not produced by this code. Generated
vectors would have passed by construction, which is the same mistake as the
first draft.

**The subject map.** Recovered from `config/harvest.json` at `fc6f1a0^`, deleted
in the same commit that archived the crawler. It is a data file again,
`source/myschool/subjects.json`, and an unmapped subject is a refusal rather
than a `slugify` guess. That file's own comment says why:

> Two lists is how a subject gets crawled under one slug and merged under
> another, which is exactly how `art`/`fine-arts` and
> `accounts-principles-of-accounts`/`principles-of-accounts` drifted apart. One
> file, read by both. A missing entry is a refusal, never a fallback.

The first draft used an identity map that was missing eleven of the twenty five
JAMB subjects, and mapped `use-of-english` to itself rather than to the site's
`english-language`. That is 167 questions, the largest subject in the bank,
requesting a url that returns 404.

**Figure hints.** The word table is from `utmelab-api-old/src/quarantine.rs`,
which records why `figure` and `table` are exact words, `diagram`, `graph` and
`sketch` take a plural, and `illustrat` is a stem. The first draft used a bag of
collocations and measurably missed rows the proven rule catches.

**Entity decoding.** `harvest.py` unescapes each text run *before* measuring it,
and says so: `&ldquo;` is nine characters in the source and one in the output,
so measuring on the raw string puts every later offset too far right. The first
draft decoded at the end, which dropped the underline from any stem with an
entity before it. The site's `<h1>` pads the stem with `&nbsp;` paragraphs, so
that was every stem.

Also ported, having been missed the first time: the cloze rule from
`harvest.py` (about the instruction, not the word "passage"), the numbered-gap
check from `quarantine.rs`, the inline-stimulus exemption, subscript and
superscript and strikethrough marks, and a `<br>` that becomes a space.

## Still to port

Named so they are not rediscovered as new work.

| Missing | Reference | Consequence |
|---|---|---|
| The html detail parser does not work on the real site | `tools/harvest.py:65-90` (`<h1>` plus a bounded option `div`) | `fetch_via_html` returns nothing for every question |
| `merge_texts` cannot join mark-bearing fragments | `harvest.py:258` takes `list[dict]` and shifts offsets | no passage ever carries a mark |
| `underline_missing` refusal | `quarantine.rs:56` | a stem that says "the underlined word" with no underline ships unanswerable |
| option count by exam era, four not a range | `quarantine.rs:176`, `mechanical.py:62` | 11 committed rows are wrong |
| `novel_leak` refusal | `quarantine.rs:230` | a novel question filed in the subject bank; the live scrape above found one |
| `has_numbered_gap` wired into the gate | `quarantine.rs:205` | a re-harvest can reintroduce the cloze rows |
| `dedupe` never refuses anything | `quarantine.rs:151`, `import.rs:122` | the first draft wrote a fingerprint column and returned ok unconditionally |
| catalog parser by structural blocks | `import_syllabus.py:43-50` | the first draft makes `contents` a topic, twice, which is a primary key collision |
| catalog uniqueness across subjects | `import_syllabus.py:127` | two subjects offering "Population" collide |
| objective paper counts, topic weight | `import_syllabus.py:171`, `:261` | every subject reads as uncounted |
| backup, re-read, rollback | `tools/review.py:323` | the json sink writes straight onto the live path |
| `duplicate_fingerprint` and `unparseable` are declared but never produced | `vocab.py` | a metric grouping on them has empty buckets |

## Decisions

| Question | Decision | Why |
|---|---|---|
| Package name | `utmelab-bank` | the noun both sides must agree on, unclaimed by the API |
| Unit of work | task, not capability | capability is worth keeping for later |
| Substrate | the bank database | JSON proved the idea, it does not ship |
| Staging | its own tables in the bank database | a bad run damages staged rows only |
| Lifecycle | raw, work, ready as tables | a wrong where clause cannot reach a verified row |
| Raw dedupe key | source url, item id, payload hash | upstream edits become visible instead of silent |
| `scrape` writes | raw lane only, then `intake` moves them | a re-scrape cannot collide with work in flight |
| Step order | decided last | prove each task alone, then compose |
| Missing dependency | refuse and name it | no task calls another |
| Reuse | tasks cannot import tasks | sharing must go through a shared module |
| SQL | only in `store` | the pipeline had four modules bypassing its own repository |
| Content hash | ported from `bank/model.rs`, vectors read from the committed bank | the API joins on it and never recomputes it |
| Subject map | a data file, recovered from `config/harvest.json` | two lists is how a subject drifts between crawl and merge |
| An unmapped subject | a refusal | a `slugify` guess is a decision nobody made |
| Porting | cited, not reinvented | a re-derived solution is a second bug |
| Contract version | read only, never written | `meta` is the API's table and it stamps its own |
| Media store | the git clone itself | one copy of every byte |
| Media url in the bank | ours, not the provider's | moving hosts is config, not migration |
| Media project | private gitlab, one commit, no history | size and speed matter more |
| Media safety | database manifest plus report | history is not the safety net |
| Media upload | written, disabled, probe first | needs its own session |

Superseded: the earlier `stage_` prefix, replaced by the lane prefixes.

Open: the media project group and name. Open: how large figures get before
transform-before-commit needs git lfs.

## Status

The spine is built and tested: config, errors, the model layer, the contract
reader against the real `src/store/schema.rs`, the store with its lane DDL and
selector vocabulary, both sinks, the source registry with the myschool parser,
the task registry with the gate and promotion, the text seams, and the media
store.

Still to build: `intake`, the media tasks, the model tasks with their runner and
prompts, the review workbench, and the `goal` composition written last.

Run `make check`, `make contract`, `make tasks`.
