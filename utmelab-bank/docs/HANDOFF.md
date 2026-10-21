# utmelab-bank handoff

**Date:** 21 October 2026
**Status:** read this before changing anything. It records what was measured, what was built, and what is wrong.

**Read `DESIGN.md` first.** It says what the bank should be, derived from the
current production source. This file records what was measured and built, and
it is the older of the two.

---

## 1. What utmelab-bank is

A **content factory**. It produces exam question bundles for the UTME Lab API to serve.

It is **not** the API. It sits beside `utmelab-api-old/` and `src/` in this repository.

```
utmelab-api/                 the serving API (Rust). Reads production Turso, serves questions.
utmelab-api-old/             the ARCHIVED tree. A source of capabilities, never of structure.
utmelab-bank/                 THIS. The Python factory. Builds and checks content.
utmelab-bank-failed/         the previous attempt. Read FINDINGS.md; do not copy its code.
utmelab-pipeline/             an earlier parallel attempt. Also do not copy.
tools/                        the pre-bank tooling. Contains the original harvester.
```

**Which source is current.** `src/` at the root of this repository is the
current production server. `utmelab-api-old/` is the archived tree, and
`docs/NOTES.temp.md` says so: "The old tree is a source of capabilities,
never of structure." The citations in this file to `utmelab-api-old/src/`
point at history. The current equivalents are listed in `DESIGN.md` section 10.

The archived tree is still worth reading for the decision log, the rich text
rule, the figure rules and the gate, because the current server does not carry
that reasoning with it.

**The Rust is not finished.** It is an MVP, built so it can serve while the
work continues. So its internals move, and the design does not hang on them.
What the content must look like is the stable part.

### The two databases

| Database | URL | Who owns it | What it holds |
|---|---|---|---|
| **Production** | `turso://utmelab-api-ultimatekristency.aws-eu-west-1.turso.io` | the API | 2,243 questions, the catalog, 2,268 verifications |
| **Bank** | `turso://utmelab-bank-shedrackgodstime08.aws-ap-south-1.turso.io` | us | one table, `staging_items` |

We **read** production. We never write it. The catalog lives there and it is the only authority for topic placement.

**One correction to the picture above.** The bank does not merely read
production. The current server declares the content tables as reads and never
creates them, and the production notes say the pipeline owns and creates
them. The bank is that pipeline, and the sixteen content tables are its
tables. `DESIGN.md` section 1 has the full arrangement.

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
- The **ready bundle**: a set of questions that are gated, reviewed, placed and
  identified, so that putting them in the served tables is a mechanical step

### Explicitly out of scope, stated by the user
- **Human verification writes to the production database.** The review step is
  ours, the placement of the record is not.
- **Promotion from utmelab-bank to the production database.** Not being built.
  Moving a row to production and making the API serve it as `verified` is a
  separate piece of work.
- **The Rust.** We read it to learn the shape the content has to take. We do
  not build it, and it is not finished: it is an MVP so it can serve while the
  work continues, so its internals are a moving target and the design does
  not hang on them.

Everything below about promotion is background, not a task list.

**The stage we are at is filling the bank.** The API is useless without
content. The measure of success is content that is complete, correct, placed
and reviewed.

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

### 3.4a How images actually work

**There is no image column and no media table. A figure is a mark on the stem.**

71 of the 2,243 questions carry an image mark. Every one looks like this:

```json
{"start":0,"len":0,"kind":"image",
 "url":"https://myschool.ng/storage/classroom/tzZCvA5EI0BAvOS0qdtp1cius4OlVxB3brjAOIqD.png",
 "position":"above"}
```

Facts to hold:

- The image is a **zero length anchor**. `len` is always 0 for an image.
- `start` is 0 for `above`, and the character count of the stem for `below`.
- `position` is `above` or `below`. It is **required**, there is no default. D55 records the measurement: above 1400, below 144. Assuming one misrenders one row in eleven.
- The url is **absolute https**. The importer refuses a relative url: "image is not an absolute URL".
- **Every image in production is `position: "above"`.** The 71 rows are all above.
- The url points at **myschool.ng**, the source site. Nothing is copied into our storage. There is no media table, no media row, no asset record anywhere in production.

Where the position came from, and this matters: the importer read it off the stem's own prose. `src/import.rs`:

```rust
fn image_position(text: &str) -> ImagePosition {
    if text.to_lowercase().contains("below") { ImagePosition::Below }
    else { ImagePosition::Above }
}
```

So a figure's placement is **guessed from the wording of the question**. "the diagram below" gives below, everything else gives above. That is the "wording is not data" trap the architecture warns about, and it is already baked into the 71 production rows.

**Nothing in production stores the bytes of a figure.** If myschool.ng drops a file, that question renders a broken image forever. That is the case for a real media store, and the case for hashing and describing the bytes ourselves.

### 3.4b The figure rule

The importer refuses a row whose stem mentions a figure but carries no image mark:

```rust
let carried_image = stem.has_mark(|k| matches!(k, InlineKind::Image { .. }));
if !carried_image && mentions_figure(&text) {
    refusals.note("needs a figure we do not have", text.clone());
    return None;
}
```

`mentions_figure` looks for these substrings, case-insensitively: `diagram`, `figure`, `graph`, `illustrat`, `shown`, `sketch`, `table`.

Two consequences:

1. A question that says "shown below" and has no image is **refused at the gate**, not admitted broken.
2. **The production bank is a filtered output, never a representative sample.** D61 says this in as many words: "no decision about what content looks like may be inferred from it". Our fixture source is a sample of the same kind. Neither tells you what real content looks like.

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

`text_norm` is the **full-Unicode** lowercase of the stem, the same as Rust's
`.to_lowercase()` and Python's `.lower()`.

**Not** SQLite's `lower()`. That one is ASCII only, and 41 live rows prove
the difference: a stem with a `Δ` or a `Ụ` in it has a `text_norm` the SQL
function would never produce. So the bank writes `text_norm` in Python and
never dedupes in SQL with `lower(text)`. It compares the `text_norm` column,
which is indexed, and which holds the full-Unicode value.

### 3.7a The fingerprint is verified against every production row

Not a sample. All **2,243** rows, recomputed from the live database with our own model classes and our own `content_fingerprint`, compared against the `content_hash` production stored. **2,243 of 2,243 match.**

That covers the cases a sample misses: 50 rows with no explanation, 2,189 with a trap, 71 with an image mark.

The check is a test, not a script. `tests/live/test_production_fingerprint_live.py` runs it against the live database when `UTMELAB_LIVE=1` is set.

Two production rows are also pinned offline, in `tests/test_hashing.py`, with the exact hash production stored, so the behaviour is frozen without a network.

This check found two real bugs in our model. Both are fixed, and both are now regression-tested.

**Bug one: we stripped whitespace from content text.** `DomainModel` carried `str_strip_whitespace=True` in its config, so pydantic trimmed every string field on every model. Two production rows carry a leading space in the explanation, `q_claim_2025_economics_76626` on the body and `q_claim_2025_hausa_75937` on the key point. We stripped it, so our hash could never equal production's.

Production stores those bytes verbatim. D60 says "`text` stays plain, so grep, diff, equality and search keep working", and a silent strip breaks exactly that.

Fixed by taking the strip off the base model and putting it back only on the types that carry identifiers, `NonEmptyStr` and `Slug`. Content text is now `Text`, which preserves the string exactly.

**Bug two: we rejected two marks on the same range.** Our validator required marks not to overlap at all. D60 says marks may share an identical range, and names the case: bold on top of underline. Production sorts by `(start, len)` and refuses only *partial* overlap.

Our validator now mirrors production's `RichText::validate` exactly: bounds are checked, partial overlap is refused, identical ranges are allowed.

Also fixed while in there: `Mark.url` was an `HttpUrl`, which normalises `https://example.com` to `https://example.com/`. The url is hashed, so a normalised url is a different row. It is now a plain string, validated as absolute `https` the way production validates it.

### 3.8 Passages

This is the part the earlier draft of this handoff left out. A passage is a stimulus a question depends on. Without it the stem can be unanswerable.

The table (`utmelab-api-old/docs/DB_SCHEMA.md`, phase 3a):

```sql
CREATE TABLE passages(
  id TEXT PRIMARY KEY,
  exam TEXT NOT NULL, subject TEXT NOT NULL, year INTEGER NOT NULL,
  kind TEXT NOT NULL, title TEXT, author TEXT,
  text TEXT NOT NULL, inline TEXT NOT NULL DEFAULT '[]'
);
```

Same `text` + `inline` split as the stem. There is no `options`, no `answer`, no `content_hash` on a passage. A passage is never served as a question and never verified on its own.

Production has **8 passages** and 4 kinds:

| kind | count | total chars | what it is |
|---|---|---|---|
| `Comprehension` | 3 | 2,391 | a story or article, questions read against it |
| `Cloze` | 3 | 1,535 | a text with gaps, the question asks for the word |
| `ReadingText` | 1 | 440 | a text used for the reading section |
| `Data` | 1 | 233 | a data set, the question reads a number off it |

The eight rows:

| id | kind | title | questions |
|---|---|---|---|
| `psg_jamb_2025_eng_comprehension_1` | Comprehension | Passage A | 5 |
| `psg_jamb_2025_eng_comprehension_2` | Comprehension | Passage C | 3 |
| `psg_jamb_2025_eng_birds_1` | Comprehension | Bird calls | 5 |
| `psg_jamb_2025_eng_cloze_1` | Cloze | Passage B | 1 |
| `psg_jamb_2025_eng_cloze_2` | Cloze | Passage D | 3 |
| `psg_jamb_2025_eng_cloze_3` | Cloze | Passage C | 9 |
| `psg_jamb_2025_eng_reading_1` | ReadingText | The Lekki Headmaster | 1 |
| `psg_jamb_2025_commerce_data_1` | Data | Working capital data | 1 |

**Titles are not unique.** `Passage C` is used by two different rows, one Comprehension and one Cloze. Key on the id, never on the title.

**28 questions link to a passage** through `questions.passage_id`. Every linked question's subject matches its passage's subject, without exception. 27 are use-of-english, 1 is commerce.

Every passage has `inline = '[]'`. No passage carries a mark of any kind, image or otherwise. Passage text holds its own paragraph structure, blank lines included, per D60.

**The serving contract** (`src/core/models/wire.rs`): `RenderedQuestion` carries `passage_id: Option<String>` and the doc comment says it plainly:

> A stimulus this row belongs to: fetch it, never ignore it: the stem may be unanswerable without it.

So the API does **not** inline the passage into the question. The consumer must make a second call. Our bank must model a passage as a first-class object, not as a string pasted into a stem.

Cloze passages mark their gap inline in the plain text, with four dots: `... the court had declared him .... Within a year the family had left the village`. The dots are data, not markup.

The `section` column is a separate idea and is not the passage kind. 145 questions carry a section, and the values are paper sections such as `Antonyms` (26), `Consonants` (19), `Comprehension` (8), `Rhymes` (7), `Basic Grammar` (6), `Cloze` (4), `Emphatic Stress` (2), `Reading Text` (1). A question can have a section and no passage, and a passage can hold questions from several sections.

---

## 4. Where our models do not match production

Fixed in commit `397030a`:

| Ours was | Production | Now |
|---|---|---|
| `Mark.length` | `Inline.len` | `len`, fixed |
| `Mark.asset_id`, a sha256 | `InlineKind::Image{url, position, alt}` | `url`, `position`, `alt`, fixed |
| `Mark.kind`, an enum | a lowercase string, flat | `MarkKind` serialises lowercase, fixed |
| `content_fingerprint()` from the architecture doc | `Question::content_fingerprint()` | replaced, verified byte for byte on **all 2,243** production rows |
| no `text_norm` | `questions.text_norm` | produced, fixed |
| `MediaAsset`, `MediaRef` | no media table at all | new ground, nothing to match |

Fixed after the full production check:

| Ours was | Production | Now |
|---|---|---|
| `DomainModel` had `str_strip_whitespace=True` | text is stored verbatim | the strip is off the base, on the identifier types only |
| `RichText` refused any overlap | identical ranges are allowed, partial overlap is refused | mirrors production's `validate` |
| `Mark.url` was an `HttpUrl` | the url is a raw string | plain string, validated as absolute https |

Still open:

| Ours | Production | The gap |
|---|---|---|
| `Option.id` is `"A"`, `"B"` | `answer` is `"a"`, `"b"` | production ids are lowercase, our fixtures are uppercase |
| `RichText.marks` | `RichText.inline` | **our JSON key is `marks`, production's is `inline`.** The mark list inside is identical, the key is not. The staging payload is ours, so it is consistent, but it is not the shape the live tooling reads. |
| `Content.stem` is one `RichText` | `text` and `inline` are two columns | production splits the stem on write, we still write one blob |
| `Content.options` is 2 to 6 | the importer's gate is 2 to 5 | we allow one option more than production accepts |
| `Passage` is `{id, text, source_item_id}` nested inside `Content` | `passages` table with `exam, subject, year, kind, title, author, text, inline` | **our passage is a fragment, production's is a catalog object with a kind and a title.** Production links by `questions.passage_id`; we nest the whole thing in the question. |
| `Content.source_explanation` is one `RichText` | `explanation` is `{key_point, body, trap}` | the reviewed `Explanation` matches, the pre-review source explanation is flat |
| `CatalogTopic.id` and `.slug` are separate | only `slug` | ours is redundant but harmless |
| `CatalogSnapshot.version` | no version column | ours is computed, fine |

The passage gap is the one worth solving first. A passage is not text that belongs to a question, it is a shared object with a kind, a title and its own questions pointing at it. Production's `passage_id` reference is the shape. Ours cannot represent two questions sharing one passage, and it cannot carry `kind`, which is what tells a consumer whether the passage is a cloze with gaps or a data set to read a number off.

---

## 5. What has been built

`utmelab-bank/src/utmelab_pipeline/`

```
domain/
  enums.py                    the fixed vocabulary
  models/                     every model, defined once
  gate.py                     THE GATE. The rules, pure, no I/O.
  hashing.py                  the content fingerprint
  state.py                    the state machine
  capabilities.py             the capability names and their requests
  ports.py                    the ports the adapters implement
  selector.py                 the selector
adapters/
  catalog/client.py           the turso_serverless driver
  catalog/production.py       the production catalog reader
  gate_service.py             runs the gate over a staging item
  media/                      git store, ingest, describe, consensus
  providers/                  the mock and the OpenCode provider, tagging
  sources/fixture/            the fixture source
  store/schema.py             the one table
  store/staging.py            save, load, transition, list by state
config.py
```

### 5.1 The gate

Built, and the plan's first item is done. It lives in `domain/gate.py` and
`adapters/gate_service.py`.

**Strict, machine only, and total.** The default is fail. Every rule that can
detect a defect can block a row. A rule that cannot tell a real defect from an
ordinary word fires as a **judgement**: it blocks, and a person clears it
with a recorded reason. The `Clearance` model carries the rule, the person
and the reason, so a decision never dies with the row.

**Every refusal goes to the same person, a defect and a judgement alike.**
The gate refuses, and the person either fixes the content or records a
clearance. One queue, one mechanism, and nothing leaves the bank without a
person having looked at it. The severity stays on the issue, so the counts
still say what was objectively broken and what needed judgement.
`GateService.queue()` is what the person works through.

**Two lines, not one.** The model refuses an out of bounds mark, a partial
overlap, an answer that names no option and a relative image url before the
gate ever sees them. The gate carries the same rules as the second line, and
each rule is a pure function over plain values so it can be judged on its
own. The rules the model does not enforce are the gate's own: exactly four
options, an explanation present, an exam named, marks in range, no markup, a
subtopic that exists under the right exam and subject, a passage that exists,
and no duplicate by id, by hash or by near-duplicate.

**Measured against the live bank.** The gate was run over all 2,243 live
production rows, and the counts are pinned by
`tests/live/test_gate_live.py`:

| Rule | Rows | Severity |
|---|---|---|
| `explanation_missing` | 50 | defect |
| `option_count` | 11 | defect |
| `cloze_without_passage` | 9 | judgement |
| `missing_figure` | 2 | judgement |
| `exam_empty` | 1 | defect |

**2,178 of 2,243 live rows pass.** The 65 that do not are exactly the rows
that cannot be reviewed into service: the 50 with no explanation, the 11 that
do not have four options, the 2 that mention a figure they do not carry, the
9 that name a gap with no passage, and the 1 withheld row.

**It agrees with the live rules.** `tools/review.py` is the tool that writes
today's verification records, so its rules are the ones in force. Run over
the same rows, the bank and the live tool agree exactly on `option_count`
(11), `cloze_without_passage` (9) and `missing_figure` (2). The bank is
stricter by 51 rows: the 50 with no explanation and the 1 withheld row, both
of which the live tool catches later, at the review step rather than at the
gate.

**One thing the live tool got right and the gate copies.** The figure rule
fires on the word "table" in a stress question, which is not a figure. It
still fires, because a rule that guessed would let a real missing figure
through, but it fires as a judgement, so a person clears it in seconds.

### 5.2 The passage as its own object

Built. The plan's second item.

**The shape is production's, column for column.** `Passage` carries `id`,
`exam`, `subject`, `year`, `kind`, `title`, `author` and `text`, with the text
a `RichText` like everything else. The kind is a closed enum of production's
four: `Comprehension`, `Cloze`, `ReadingText`, `Data`.

**A question names a passage by id.** `Content.passage_id` is a reference, and
`StagingItem.passage` carries the passage the item introduces. The model
refuses an item whose content names one passage and carries another.

**The bank owns a `passages` table.** It is the second table, beside
`staging_items`, and it is keyed by the passage id, so two questions that
share a passage share one row. Production does exactly that: 8 passages, 28
questions. `StagingStore.passage_ids()` is the gate's known set, and
`StagingStore.load_passage()` reads one by id.

**The table grew, so there is a migration.** The live bank database already
had a `staging_items` table without the `passage` column, and SQLite has no
"add column if not exists". `schema.MIGRATIONS` names the column and the
statement, and `ensure_schema` checks the column list first. The migration
was run against the live bank database and the column is there.

**It was verified against the live bank database.** A passage was written,
the staging row was read back, the passage was read by id, and the rows were
cleaned up.


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
  store/schema.py               the bank's tables and their migrations
  store/staging.py              save, load, transition, list by state
```

`utmelab-bank/tests/`

```
conftest.py                     fixtures
test_models.py                  model validation
test_state_machine.py           transitions, the content hash
test_hashing.py                 canonical json
test_gate.py                     the gate rules
test_passage.py                  the passage as its own object
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
contract/test_gate_service.py        the gate service
live/test_opencode_live.py         a real model call, skipped unless UTMELAB_LIVE=1
live/test_production_fingerprint_live.py
                                   every production row must hash the way we
                                   hash it, skipped unless UTMELAB_LIVE=1
live/test_gate_live.py             the gate must see what the live bank shows,
                                   skipped unless UTMELAB_LIVE=1
```

**197 tests pass, 3 skipped. mypy strict is clean across `src` and `tests`.**

The three skipped are the live tests: the OpenCode smoke test, the
production fingerprint contract and the gate contract. All run with
`UTMELAB_LIVE=1`.

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
2. **Where media lives.** Production stores no media. The GitLab media repository is new ground, so the URL convention has to be decided: does the image mark carry the GitLab URL, or a CDN URL that points at it?
3. **The image position.** Production guesses it from the stem's prose. Do we inherit that, or do we ask the human reviewer? Guessing means a question that says "the diagram below" renders the figure above the stem. That is a real bug in production, and copying it deliberately is a choice. **The current server has already settled it**: `src/core/models/domain.rs` says "Where the figure renders relative to the stem. Data, never inferred." So the position is a field the reviewer sets. The question is now only whether the bank's reviewer sets it, and how.
4. **Whether we copy figure bytes at all.** Production points at myschool.ng and copies nothing, so the figures are one dead host away from being permanently broken. A media store fixes that, at the cost of downloading and describing every figure. The 71 rows are small enough to do it in one pass.
5. **The `marks` versus `inline` key.** Rename our key to `inline` so the staging payload is the shape the live tooling reads, or keep ours because the staging table is ours. The mark list inside is already identical. **The live tooling decides it**: `tools/review.py` reads `q["text"]["inline"]` and writes the verification records against that shape. A payload the bank cannot hand to the existing tool is a payload that is not ready.
6. **The passage shape.** Our passage is nested in the question, production's is a catalog object linked by id. Changing it means two questions can share one passage, which is the case production has 28 times.
7. **Where the bank runs the gate.** The server does not validate rows at all, and the server's own test proves a malformed row fails the whole read. So the gate has to be airtight, and it has to be in the bank. The live rules in `tools/review.py` are the specification, and the bank should implement those rather than the archived import rules.
8. **Who signs off, and how a ready bundle gets placed.** The serving predicate counts only a human pass, and the production notes say human verification writes are not the serving app's job. So a person is on the critical path, and someone places the bundle. Both are outside our scope. What is ours is making the bundle complete enough that placing it is mechanical.

Decided and done, previously listed here:

- **The mark shape.** Our `Mark` now uses `len` plus a URL and a position for images, matching production. Done in `397030a`.
- **The content hash.** Ours is now the production algorithm, verified byte for byte against **all 2,243** production rows. Done in `397030a`, re-verified after the whitespace fix. It now agrees three ways: production's stored hash, `tools/review.py`'s `content_fingerprint`, and ours, on every row.
- **The option id case.** Still open. Production uses lowercase, our fixtures use uppercase. This is a one-line change in the fixtures plus a constraint on `Option.id`.

---

## 9. Traps

Things that cost time. Do not walk into them again.

- **Two classes with one name.** Earlier there were duplicate `CatalogRef`, `Evidence`, `SourceProfile` and even duplicate `Content` inside one file. Pydantic then failed with "Input should be a valid dictionary or instance of X" for a value that plainly was one. Every model is now defined exactly once, in `models/common.py` or `models/proposals.py`. Keep it that way.
- **A forward reference that resolves to the wrong class.** `Evidence.verifications` was typed `"VerificationRecord"` and Pydantic resolved it to the `Verification` in `validation.py`. The fix was to delete the duplicate and merge the two classes, keeping the trust rules.
- **`model_copy` does not validate.** It is the fastest way to put a bad value into a model. Use `model_validate` when a validator must run.
- **A state that is free text.** `StagingItem.state` was a string and any string passed. It is now the `State` enum, and `transition_to` refuses an invented move.
- **`is` on enum values.** `transition_to` compared with `is` and stored the raw argument, so a string target landed as a plain `str`. It now coerces to `State` first.
- **A model wide strip rewrites content.** `DomainModel` carried `str_strip_whitespace=True`, so pydantic trimmed every string on every model. Two production rows have a leading space in the explanation, and trimming it changed the fingerprint, so those two rows could never match production. **A sample of 394 rows missed it, because those two rows were not in the sample.** Check against everything, not a slice.
- **SQLite's `lower()` is ASCII only.** 41 live rows have a `text_norm` that SQLite's `lower(text)` would never produce, because the stem carries a `Δ` or a `Ụ`. Python's `.lower()` and Rust's `.to_lowercase()` are full-Unicode and do produce it. **Never dedupe in SQL with `lower(text)`.** Compare the `text_norm` column.
- **The archived tree is not the current source.** `src/` at the root of the repository is the current server. `utmelab-api-old/` is the archived tree, and `docs/NOTES.temp.md` says so: "a source of capabilities, never of structure". The archived `import.rs` gate rules and the live `tools/review.py` gate rules are **different**, and the live ones are in force.
- **The live gate flags, it does not refuse the row.** `tools/review.py` refuses to *verify* a quarantined row, which is different from refusing the row. The archived import gate refused at the door. The live behaviour is the safer one, because the figure hint words collide with ordinary English: "table" in a stress question is not a missing figure.
- **The server does not validate rows.** It deserializes and type-checks. A mark past the end of its text, an answer naming no option, a stem with HTML, all get served happily. And a row whose `options` is not valid JSON fails the whole read, so one bad row breaks the endpoint for every consumer. There is no second line of defence.
- **The live DDL is the spec, not `BANK_DDL`.** The server's test fixture DDL has no primary keys and no `NOT NULL`, on purpose, so a test can insert a partial row. The live tables have both. The pipeline creates the live shape.
- **A url type that normalises.** `Mark.url` was an `HttpUrl`, and `HttpUrl("https://example.com")` is `https://example.com/`. The url is hashed, so normalising it silently changes the row. Anything that is hashed must be stored verbatim.
- **"Must not overlap" is not the rule.** D60 allows two marks on the same range, and names the case, bold on top of underline. Production refuses only *partial* overlap. Our validator was stricter than production and would have refused a legitimate row.
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

UTMELAB_LIVE=1 python -m pytest tests/live/ -q   # a real model call, and the
                                                # production fingerprint check
```

The live production fingerprint check is the one worth running after any change
to a model, a validator or the hashing. It recomputes the hash of all 2,243
production rows with our own code and compares it against the hash production
stored. If it fails, the change broke the contract.

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

## 11. The rest of the bank, measured

Everything below was counted against the live production database, not read from a document.

### 11.1 The question rows

| Column | What production holds |
|---|---|
| `source` | `claimed_paper` 2,079, `imported` 97, `authored` 67. No `past_paper` rows exist, even though the schema comment names it. |
| `year` | **Every row is 2025.** D52: the cohort the question is prepared for, not the year it was lifted from. |
| `exam` | `JAMB` 2,241, `WAEC` 1, `''` 1. The empty one is withheld and never servable (D21). |
| `difficulty` | 3 for 2,113 rows, 2 for 82, 1 for 43, 4 for 5. Heavily concentrated on 3. |
| `marks` | 2.5 for 2,096 rows, 1.0 for 87, 2.0 for 52, 3.0 for 8. |
| `options` | 4 options for 2,232 rows, 3 for 8, 5 for 2, 2 for 1. The importer's gate is 2 to 5, and all three extremes really occur. |
| `explanation` | Present on 2,193 of 2,243. 50 rows have none. |
| `subtopic_id` | Null on 3 rows. No row has a subtopic slug that does not exist. |

The 3 rows with no subtopic fail the serving predicate, so they are invisible to consumers even though they are in the table. A foreign key is not enforced here.

### 11.2 What is servable

Applying the production predicate to the live data: **2,189 of 2,243** rows are servable.

The 54 excluded rows break down exactly:

| Rows | Why they are not servable |
|---|---|
| 50 | No explanation. The review step refuses to verify a row with no explanation, so these were never verified and their hash matches nothing. |
| 1 | `exam` is empty, so the row is withheld (D21). |
| 2 | No subtopic, so the row is not attributable to a topic. Also among the 50 with no explanation. |
| 1 | No subtopic, but it does carry a matching verification hash. Unattributable, but verified. |

2,243 minus 50 minus 1 minus 3 is 2,189, so nothing else is filtering anything out. 53 rows have no verification whose hash matches their current content, and 50 of those are the rows with no explanation. The mechanism working, not broken.

Every verification in the table has the same shape: `kind='human'`, `verdict='pass'`, `scope='["answer","explanation"]'`. 2,268 rows, all identical. There is no `machine` kind, no `fail` verdict, no partial scope. The `scope` machinery is fully general in the Rust code, but the data uses exactly one shape.

`content_hash` matching is part of the predicate, so a row whose text changed after verification drops out of service until someone verifies it again. That is the point of the column, and it is why our fingerprint had to be byte-exact.

### 11.3 Blueprints are not usable yet

80 blueprint rows, and **none of them is `measured`**:

| level | status | rows |
|---|---|---|
| `topic` | provisional | 31 |
| `section` | provisional | 30 |
| `subject` | unmapped | 19 |

`readiness.rs` computes `need = ceil(expected)` against the number of distinct fingerprints over servable, in-scope, attributed rows. With every blueprint `provisional` or `unmapped`, **readiness cannot be computed from this table.** Do not build a readiness dashboard on it yet. The `expected` columns exist but are not authoritative.

### 11.4 Countries and requirements

`countries` holds 5: NG, GH, SL, GM, LR.

`exam_requirements` holds 2 rows, both for JAMB in Nigeria:

```
JAMB NG core     min_select 1  subjects ["use-of-english"]
JAMB NG elective min_select 3  subjects []
```

`topic_countries` is **empty**. The serving predicate checks a topic's allowed countries through that table, so today the check passes for every topic. It is a live rule with no data behind it, not an unused rule.

### 11.5 Novels

6 novels, 220 novel questions. The schema (DB_SCHEMA.md phase 3b) splits a novel into nine tables: `novels`, `novel_chapters`, `novel_characters`, `novel_themes`, `novel_questions`, and the rest.

`novel_questions` uses the same `text` + `inline` split as questions, and **not one of the 220 rows has a mark**. Only 54 have an explanation. `novels.cover_image` is a plain column, not a mark, and there is no image table.

The served shape is `RenderedNovelQuestion`, with the same withholding contract: no `answer` and no `explanation` unless asked for. `novel_id` is filled by the caller, the stored row does not carry it.

Novels are out of scope for the bank. But the D60 rule says novel-question text takes the identical `RichText` shape, so if we ever model them, there is no new type to invent.

### 11.6 The full table list

The live database holds 21 real tables, in two groups. The split is by
ownership, and it is the same split the current server's code draws.

The five the **server** creates and owns:

```
meta  api_keys  dashboard_users  sessions  reports
```

The sixteen the **pipeline** creates and owns, which is the bank:

```
questions  verifications  passages
subjects  exams  topics  subtopics  blueprints
countries  topic_countries  exam_requirements
novels  novel_chapters  novel_characters  novel_themes  novel_questions
```

The live table list also has `questions.text_norm`, which the current server
does not read. It is a leftover from the archived tree, but the bank should
still write it, and should write it in Python's full-Unicode `.lower()`.
Section 3.7 has the SQLite `lower()` trap.

### 11.7 The trust boundary, measured

**The current server does no semantic validation of a row.** The reader in
`src/store/catalog.rs` deserializes the JSON columns and type-checks the
scalars. It does not check that a mark fits inside its text, that the answer
names an option, that there are four options, that the subtopic exists, or
that the text carries no markup. There is no `validate` on a row anywhere in
the current source.

The server's own test says what a malformed row does:

```rust
async fn get_question_rejects_bad_option_json() {
    // ... INSERT INTO questions VALUES ('bad', ..., 'not-json', ...)
    let err = get_question(&s, "bad").await.expect_err("malformed options fail loudly");
    assert!(matches!(err, crate::error::AppError::Upstream(_)));
}
```

So one bad row in the served content either **breaks the endpoint for every consumer**, or
**is served as wrong content**. There is no second line of defence. The
gate is the only defence, and it is the bank's.

### 11.8 The gate rules in force, measured

The live rules are in `tools/review.py`, not in the archived Rust. Run against
the 2,243 live rows, they flag:

| Flag | Live rows |
|---|---|
| `option_count`, not exactly 4 options | 11 |
| `missing_figure`, a figure mentioned and none present | 2 |
| `underline_missing` | 0 |
| `novel_leak` | 0 |
| `cloze_without_passage` | 0 |
| `duplicate_stem` | 0 |

One of the two `missing_figure` flags is a false positive. The word "table"
in a stress question's last option trips it.

### 11.9 The scale facts, measured

`/api/v1/public/exams` and `/api/v1/public/summary` are keyless, and they
scan the whole `verifications` table with two `json_each` passes and a
sorter. On the live remote at 2,268 verifications that is **0.75 s**.

On a local replica of the same data and the same queries:

| Population | `public_exams` |
|---|---|
| 2,243 questions, 2,268 verifications | 0.038 s |
| 22,430 questions, 22,680 verifications | 0.461 s |
| 112,150 questions, 113,400 verifications | 2.046 s |

Linear, and the remote engine is about 19 times slower than local sqlite on
the same data.

Two index facts:

- **There is no index on `questions.content_hash`.** A hash lookup is a full
  scan, 0.081 s at 112,150 rows. With an index it is 0.000 s. The bank
  creates the index, so this is the bank's call.
- `idx_ver_kind (kind, question_id, created_at DESC, id DESC)` turns the
  public aggregate's `SCAN verifications` into a `SEARCH`, and removes the
  sorter.

And the rule that follows: **production's `verifications` table holds human
verifications only.** The bank's AI evidence stays in the bank. Every AI row
written into production's table is a row the public route scans, for a row
that can never change a served answer.

There is **no media table, no media_assets table, and no image column** anywhere.

---

## 12. Where the doctrine comes from

### 12.1 The docs trail for inline rich text

Every place the old code decided something about rich text, and what it said:

| Doc | What it decides |
|---|---|
| `utmelab-api-old/docs/QUESTION_BANK_DECISIONS.md` **D60** | The core rule. Every text-bearing field is `RichText { text: String, inline: Vec<Inline> }` with `Inline { start: u32, len: u32, kind: InlineKind }`. **Stems, every option, `key_point`/`body`/`trap`, passage text and novel-question text all take the identical shape.** Offsets are Unicode characters, never bytes. Marks may share an identical range (bold+underline) but never partially overlap. Paragraph breaks are `\n\n` in plain text, no block layer. `emphasis` and `image` are deleted, not shadowed. |
| **D61** | The harvester maps markup to marks instead of deleting it. `<u>`/`<em>`/`<strong>`/`<s>` become marks, `<sub>`/`<sup>` become `Subscript`/`Superscript`, `<img>` becomes an `Image{url}` mark, block boundaries survive as `\n\n`. Also the warning that matters most: the bank is a **filtered output, never a representative sample**, and no decision about what content looks like may be inferred from it. |
| **D54** | The underlined target, originally a substring field, superseded by D60. |
| **D55** | Figures, originally `image: Option<ImageRef{url, position}>`. `position` is `above \| below`, required, no default. Placement varies: above 1,400, below 144. Superseded by D60. |
| `utmelab-api-old/docs/RICH_TEXT_HANDOFF.md` | Why one `RichText` type exists and why it must be the same type everywhere. D60 and D61 in prose. |
| `utmelab-api-old/docs/UNDERLINE_PROBLEM.md` | Why the underline mark matters and what the harvester destroyed. |
| `utmelab-api-old/docs/CLOZE_PROBLEM.md` | Why a missing passage makes a question unanswerable, and the cloze recovery. |
| `utmelab-api-old/docs/DB_SCHEMA.md` | The exact column list, and rules R1 to R9. R1: JSON columns deserialize into the same `RichText`, `Choice`, `Explanation` types, no parallel DB types ever. R4: validation moves to write time, because a database has no boot-load to validate at. R5: `verified` derives at read in Rust, never a stored flag. R6: `content_hash` is maintained on every write. |
| `utmelab-api-old/docs/REVIEW_METHOD.md` | The review loop, the gate re-run, the refusal expectations. |
| `utmelab-api-old/docs/RELEASE_BLOCKERS.md` | Every blocker between the bank and a launch, with owner and closing gate. |
| `utmelab-api-old/src/bank/model.rs` | The real types. `Inline`, `InlineKind`, `RichText`, `Explanation`, `Question`, `Passage`, `ImagePosition`, `content_fingerprint()`. **The source of truth for the schema.** |
| `utmelab-api-old/src/bank/reads.rs` | The real serving predicate, `where_clause()`. |
| `utmelab-api-old/src/bank/write.rs` | The real write path, the hash storage, `text_norm`. |
| `utmelab-api-old/src/bank/view.rs` | The shape the API serves, `render()`, and the passage contract. |
| `utmelab-api-old/src/import.rs` | The gate. Every refusal rule, the figure hint list, and how image placement was guessed. |
| `utmelab-api-old/src/quarantine.rs` | The read-only report of every mechanical defect. |
| `utmelab-api-old/src/bank/readiness.rs` | Per-topic readiness, blueprint by coverage. |

### 12.2 The current source, which is what counts

The archived tree above is where the reasoning lives. The current code is
where the contract lives. These are the files to read first.

| File | What it holds |
|---|---|
| `src/core/models/domain.rs` | The current types. `RichText`, `Inline`, `InlineKind`, `ImagePosition`, `Choice`, `Explanation`, `Question`, `Passage`, `Blueprint`, `Exam`, `Subject`, `Topic`. **The source of truth for the schema.** |
| `src/core/models/wire.rs` | The shapes the server answers with, including `RenderedQuestion` and its passage contract. |
| `src/store/schema.rs` | `READ_SHAPES`, the server's list of every table and column it depends on, and the contract check that fails closed. Also the split between the tables the server creates and the tables the pipeline creates. |
| `src/testing.rs` | `BANK_DDL`, the bank tables' DDL. The closest thing to a specification that exists. |
| `src/store/catalog.rs` | The serving predicate, spelled once: `verified_predicate` and `LATEST_VERIFIED_CTE`. |
| `src/store/sync.rs` | The replica lifecycle. The server pulls the remote on a timer, so serving never blocks on the network. |
| `docs/NOTES.temp.md` | The pipeline doctrine. It names intake, promote, gates and review. Promote is not ours, so our three are intake, gates and review, and the output is a ready bundle. |

Two sentences from the current code that settle questions the archived tree
left open:

- `src/core/models/domain.rs`: "Where the figure renders relative to the
  stem. Data, never inferred." The archived tree guessed the position from
  the stem's prose. The current code has stopped guessing.
- `src/store/schema.rs`: "The bank tables (questions, subjects, passages, …)
  are owned and created by the pipeline, so the API never creates them."

### 12.3 Our own docs

- `utmelab-bank/docs/DESIGN.md` - how the bank is supposed to be. **Read this first.**
- `utmelab-bank/docs/ARCHITECTURE.md` - the architecture this code implements.
- `utmelab-bank-failed/FINDINGS.md` - the evidence file. **Read it, but check every number against the live database.** Its row counts are stale.

