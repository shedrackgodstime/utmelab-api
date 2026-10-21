# How utmelab-bank is supposed to be

Written 2026-10-21. Built from the live production database, the current
production source in this repository, and the pipeline notes in
`docs/NOTES.temp.md`.

This document says what the bank should look like. It is not a report on what
the code does today. The gap between the two is in section 10.

---

## 1. What the bank is

utmelab-bank is the pipeline. That word is the production doctrine's own.
`docs/NOTES.temp.md` puts it this way:

> `import`, `quarantine` and `verify` are pipeline work (`utmelab-bank`'s
> intake, promote, gates and review steps), not serving work.

So the bank has four jobs, and their names come from the retired CLI verbs
they replace.

| Job | What it does | The old verb |
|---|---|---|
| **Intake** | Take content from a source and put it in the bank's shape. | `import` |
| **Gates** | Decide whether that content is sound, and say why when it is not. | `quarantine` |
| **Review** | Have a person check the content and record the check. | `verify` |
| **Promote** | Move approved content into the tables the server reads. | `import` wrote the rows |

The serving side is a separate program. It reads the bank's tables out of a
replica and answers questions about them. It never writes a bank row. The
serving code says so itself, in `src/store/schema.rs`:

> The bank tables (questions, subjects, passages, …) are owned and created by
> the pipeline, so the API never creates them: they are declared here as
> reads, not DDL.

The shape of the whole system:

```
   sources                    utmelab-bank                Turso remote          the API
   ───────                    ────────────                ────────────          ───────
   harvest ─┐
   syllabus ─┼─▶ intake ─▶ gates ─▶ review ─▶ promote ─▶ bank tables ──sync──▶ replica ──▶ responses
   inbox   ─┘                                  │
                                               └─▶ reports ──▶ back to intake
```

Promotion lands in Turso. The API pulls that remote into a local replica on a
timer, so serving never waits on the network, and a change made anywhere lands
within the sync interval.

### 1.1 The two halves of the same database

One Turso database holds both halves. The split is by ownership, not by
database.

| Owner | Tables |
|---|---|
| **The API** creates and owns | `meta`, `api_keys`, `dashboard_users`, `sessions`, `reports`. Five tables, all operational. |
| **The pipeline** creates and owns | `questions`, `verifications`, `passages`, `subjects`, `topics`, `subtopics`, `exams`, `exam_requirements`, `countries`, `topic_countries`, `blueprints`, `novels`, `novel_chapters`, `novel_characters`, `novel_themes`, `novel_questions`. Sixteen tables, all content. |

The rule behind the split, from the production notes, is worth keeping
exactly: tables the API creates are declared as `DDL`, and tables the pipeline
creates are declared as reads and validated but never created, because a
`CREATE TABLE IF NOT EXISTS` from the API would win on a fresh replica and
freeze a loose shape before the pipeline's promotion ever lands.

The bank is on the pipeline side of that line. It creates the sixteen.

---

## 2. The contract between the two halves

The pipeline and the server agree on a shape, and the agreement is checked on
every boot rather than assumed.

**`meta.contract_version`.** A single number, currently 1. The server stamps
its own value when the key is absent, and refuses to serve when the stamped
value differs from the one its binary expects. The pipeline stamps what it
promoted against, so a shape change is a deliberate version bump on both
sides.

**`READ_SHAPES`.** The server's list of every table it reads and every column
it depends on. A missing table or a missing column fails the contract closed,
on boot and on every re-check. The bank therefore has to create those tables
with those columns, and it should treat that list as the contract rather than
a description.

**The columns the server does not read.** `questions.text_norm` exists in the
live table and the server does not read it. It is a leftover from the old
tree. The bank should not build anything on it. Dedupe runs on
`content_hash`, which the server does read and does compare.

**The fingerprint is the pipeline's job.** The server never computes a content
hash. It reads the one stored on the row and compares it to the one stored on
the verification. If those two differ, the row is not servable. So the
algorithm lives entirely on the bank's side of the line, and it has to stay
byte for byte what the stored hashes already are, or every existing row falls
out of service the moment its content is touched.

Our implementation is verified against all 2,243 production rows and matches
every one.

---

## 3. The tables the bank owns

The DDL below is the one the server's own test fixtures use, which is the
closest thing to a specification that exists. The live table has more
constraints than this, and adding them is fine, but the column list and the
types are fixed by the contract.

```sql
CREATE TABLE questions (
    id TEXT, exam TEXT, subject TEXT, year INTEGER, source TEXT,
    text TEXT, inline TEXT, options TEXT, answer TEXT,
    subtopic_id TEXT, section TEXT, passage_id TEXT, explanation TEXT,
    marks REAL, difficulty INTEGER, content_hash TEXT
);

CREATE TABLE passages (
    id TEXT, exam TEXT, subject TEXT, year INTEGER,
    kind TEXT, title TEXT, author TEXT, text TEXT, inline TEXT
);

CREATE TABLE verifications (
    id TEXT, question_id TEXT, kind TEXT, verdict TEXT, scope TEXT,
    verifier TEXT, detail TEXT, content_hash TEXT, created_at TEXT
);

CREATE TABLE subjects (
    slug TEXT, exam TEXT, name TEXT,
    is_compulsory INTEGER, objective_paper_questions INTEGER
);

CREATE TABLE topics (
    slug TEXT, subject TEXT, exam TEXT, name TEXT,
    "order" INTEGER, weight INTEGER, objectives TEXT
);

CREATE TABLE subtopics (slug TEXT, topic TEXT, name TEXT, "order" INTEGER, objectives TEXT);

CREATE TABLE exams (
    code TEXT, name TEXT, countries TEXT, status TEXT,
    has_full_paper INTEGER, subjects_required INTEGER,
    duration_minutes INTEGER, rules TEXT
);

CREATE TABLE exam_requirements (
    exam TEXT, country TEXT, "group" TEXT, min_select INTEGER, subjects TEXT
);

CREATE TABLE countries (code TEXT, name TEXT);

CREATE TABLE topic_countries (topic TEXT NOT NULL, country TEXT NOT NULL, PRIMARY KEY (topic, country));

CREATE TABLE blueprints (
    exam TEXT, subject TEXT, level TEXT, topic TEXT, section TEXT, members TEXT,
    paper_size INTEGER, pct REAL, pct_low REAL, pct_high REAL,
    expected REAL, expected_low REAL, expected_high REAL,
    source TEXT, sample TEXT, method TEXT, confidence TEXT, status TEXT, note TEXT
);

CREATE TABLE novels (
    id TEXT, title TEXT, author TEXT, year_published INTEGER, exam TEXT,
    year_prescribed TEXT, category TEXT, featured INTEGER, synopsis TEXT,
    setting_place TEXT, setting_period TEXT, cover_image TEXT
);

CREATE TABLE novel_chapters (novel_id TEXT, number INTEGER, title TEXT, summary TEXT, key_events TEXT);
CREATE TABLE novel_characters (novel_id TEXT, name TEXT, role TEXT, character_type TEXT, description TEXT);
CREATE TABLE novel_themes (novel_id TEXT, name TEXT, description TEXT, evidence TEXT);

CREATE TABLE novel_questions (
    id TEXT, novel_id TEXT, chapter_number INTEGER, text TEXT, inline TEXT,
    options TEXT, answer TEXT, explanation TEXT, content_hash TEXT
);
```

Note what is not there. No media table, no assets table, no image column. A
figure is a mark.

---

## 4. The content model

### 4.1 One RichText, everywhere

`src/core/models/domain.rs` is the specification, and it says the quiet part
out loud:

> Plain text plus offset marks. `text` stays searchable as characters;
> structure rides in `inline` as Unicode-scalar offsets, never bytes.

```rust
pub struct RichText {
    pub text: String,
    pub inline: Vec<Inline>,
}

pub struct Inline {
    pub start: u32,
    pub len: u32,
    #[serde(flatten)]
    pub kind: InlineKind,
}

pub enum InlineKind {
    Bold, Italic, Underline, Strike, Subscript, Superscript,
    Image { url: String, position: ImagePosition, alt: Option<String> },
}
```

The mark serialises flat, with the kind as an adjacent tag, so a mark reads
`{"start":24,"len":6,"kind":"underline"}`.

The same shape is used for a stem, for every option, for `key_point`, `body`
and `trap`, for a passage's text, and for a novel question's text. One shape
means a consumer that has learned one has learned all of them, and it means
the bank has exactly one rich text type to get right.

Two rules on the marks. Offsets count Unicode scalar values, never bytes, so
a character outside the basic plane still counts as one. And two marks may
share an identical range, bold on top of underline is the case the old
decision log names, while a partial overlap is refused.

### 4.2 The question row

The 16 columns of `questions` and what the bank puts in each.

| Column | What goes in it |
|---|---|
| `id` | The identity. Used once. |
| `exam` | Never empty. An empty exam means the row is withheld and not servable. |
| `subject` | Must exist in `subjects` for that exam. |
| `year` | The cohort the question is prepared for, not the year it was lifted from. 1900 to 2100. |
| `source` | `past_paper`, `claimed_paper`, `authored` or `imported`. |
| `text` | The stem's plain text. |
| `inline` | The stem's marks, as a JSON array. |
| `options` | A JSON array of `{"id": "a", "text": {"text": ..., "inline": [...]}}`. |
| `answer` | An option id, never a label and never an index. |
| `subtopic_id` | A subtopic slug. Must exist in `subtopics`. |
| `section` | The paper section name. Free text. |
| `passage_id` | The id of a passage, or null. |
| `explanation` | `{"key_point": ..., "body": ..., "trap": ...}` or null. |
| `marks` | A number. |
| `difficulty` | 1 to 5. |
| `content_hash` | Derived by the bank, never authored. |

The `options` and `explanation` columns hold nested objects with their own
`inline`, while `text` and `inline` are separate columns for the stem. That
asymmetry is the real shape and it is not a mistake. The stem is the thing
that gets searched, so it is split so the search can use a plain column.

### 4.3 The verification row

| Column | What goes in it |
|---|---|
| `id` | The identity. |
| `question_id` | The question. |
| `kind` | `auto_rule`, `ai_bulk`, `ai_single` or `human`. |
| `verdict` | `pass` or `fail`. |
| `scope` | A JSON array of what was checked: `answer`, `explanation`, `topic_link`, `marks`, `bounds`, `dupe`. |
| `verifier` | A human name, a model run id, or a rule name. |
| `detail` | Free text. |
| `content_hash` | The fingerprint at check time. |
| `created_at` | When. |

**This row decides whether a question is servable.** The rule, spelled once in
`src/store/catalog.rs`:

> the newest human verification carrying both `answer` and `explanation` must
> be a pass whose `content_hash` still matches the row.

In SQL, that is the newest `human` verification whose scope covers both the
answer and the explanation, with a verdict of pass, whose `content_hash`
equals the row's `content_hash`, and with no later human verification
covering the same two things.

Three consequences the bank has to respect.

1. **A content edit voids the pass.** The hash is the receipt, so the bank
   must recompute it on every write and must never write a row whose hash
   does not match the verification that covers it.
2. **Only a human pass counts.** An AI check writes an `ai_bulk` or an
   `ai_single` row. It is signal. It never makes a row servable, and the
   bank must never write a `human` row.
3. **The scope matters.** A human pass that covers only the answer does not
   serve a question, because the explanation would be unverified.

Production holds 2,268 verifications, every one of them `human`, `pass`, with
the scope `["answer","explanation"]`. The other three kinds are supported by
the schema and unused, which tells the bank what the AI kinds are for.

### 4.4 Passages

A passage is a stimulus a question depends on. The server's own comment on the
wire type says it plainly:

> A stimulus this row belongs to: fetch it, never ignore it: the stem may be
> unanswerable without it.

The table is 9 columns. `id`, `exam`, `subject`, `year`, `kind`, `title`,
`author`, `text`, `inline`. A passage has no options, no answer, no content
hash, and it is never verified on its own.

Production holds 8 passages and 4 kinds.

| Kind | Rows | What it is |
|---|---|---|
| `Comprehension` | 3 | A story or an article. Questions read against it. |
| `Cloze` | 3 | A text with gaps. The question asks for the missing word. |
| `ReadingText` | 1 | A text for the reading section. |
| `Data` | 1 | A data set. The question reads a number off it. |

28 questions point at a passage, and one passage serves up to 5 questions.
Every question that points at a passage shares its subject, without exception.

`kind` is not decoration. It tells the consumer how to read the passage. A
cloze carries its gaps in the plain text as four dots, and that is data, not
markup. A data passage is numbers, and the question against it asks for a
figure.

So the bank holds a passage as its own object with its own row, and a
question that references it by id. Nesting the passage inside the question is
wrong on both counts. It forbids two questions sharing one passage, which
production does 28 times, and it has nowhere to put `kind`.

Titles repeat. `Passage C` names two different production rows, one
Comprehension and one Cloze. The id is the only key.

### 4.5 Figures

A figure is a mark, and the mark is the wire shape. The kind carries a url, a
position and an optional alt, and the mark is a zero length anchor: `len` is
0 and `start` is 0 for a figure above the text, or the character count of the
text for a figure below it.

The position is one of `above` or `below`, and the current type says what
that means:

> Where the figure renders relative to the stem. Data, never inferred.

That sentence is a correction. The archived tree guessed the position from
the stem's prose, looking for the word `below`, and everything else rendered
above. 71 production rows carry the result of that guess. The current code
has stopped guessing, so the bank must not guess either. The position is a
field the reviewer sets.

Production holds 71 questions with a figure, all positioned above, all
pointing at `myschool.ng`. The bytes live on that site. There is no media
table anywhere.

So the bank has two jobs around a figure, and the second one is not built
yet.

1. **The asset.** The bytes, their sha256, the mime type, the alt text, a
   description, and where they came from. The bank holds this, and production
   has no answer for it.
2. **The swap.** Until the asset exists, the mark carries the source url, and
   that renders today. When the asset exists, the mark's url is replaced with
   the bank's own url for the stored asset, at promotion.

The source url stays on the mark until the swap. A staged item always points
at something that renders.

---

## 5. The four jobs

### 5.1 Intake

Take content from a source and put it in the bank's shape, without judging
it yet.

The bank should be able to take content from several kinds of source, because
production's own tools show the range: harvested pages, syllabus files, an
inbox of claims, and passages recovered from papers. The bank's
`SourceCapability` enum already names them: `passages`, `passage_sets`,
`figures`, `option_figures`, `rich_text`, `answer`, `explanation`,
`sections`, `marks`.

Two rules for intake.

**A source states what it can carry.** The capability list is per source, not
global, because a syllabus file has no answer and a harvested page has no
subtopic. The bank asks the source, and a missing capability is a refusal,
not a guess.

**Intake does not judge.** A source may hold a row that fails a rule. Intake
puts it in the bank's shape and lets the gate decide, so the refusal is
counted and attributed rather than lost in a scraper.

### 5.2 Gates

The gate is the bank's main product. The production notes are blunt about
where it belongs: the old tree's `import` and `quarantine` verbs are pipeline
work, and the bank's gate and review steps are their successors.

The archived tree's gate refused a row for these reasons. The bank should
refuse for the same reasons, and should count every refusal rather than
dropping it.

| Reason | Rule |
|---|---|
| unknown subject slug | the subject is not in the catalog |
| empty stem | there is no question |
| invalid marks | a mark runs past the end of its text, two marks partially overlap, or an image url is not absolute https |
| option count outside 2 to 5 | the gate takes 2 to 5 options |
| answer is not one of the option ids | the answer must name an option. The archived tree's message for this one says "key points outside the options", which does not describe the check it runs. Read the code, not the message. |
| image is not an absolute url | no relative paths |
| needs a figure we do not have | the stem mentions a figure and carries no image mark |
| id already in the bank | an id is used once |
| duplicate of a question we already hold | the content hash already exists |
| year outside 1900 to 2100 | an implausible exam year |
| unknown subtopic | the subtopic does not exist in the catalog |
| html entity or tag in the text | harvest residue, refused rather than served as mojibake |
| exam is empty | the record is valid but not servable, so the bank refuses it |

The figure rule deserves its own line. The archived tree refused a row whose
stem mentions a figure and carries no image, looking for `diagram`, `figure`,
`graph`, `illustrat`, `shown`, `sketch` and `table`. That rule is why the
production bank is a filtered output and never a representative sample, so
no conclusion about what content looks like may be drawn from it.

Every refusal carries a reason and a subject, so the end of a run can report
how many rows were refused and why, the way the archived tree's quarantine
report did.

**The gate is where the hash is computed.** A gate that passes a row hands
over a row whose `content_hash` is correct, because the hash is the receipt
every later stage depends on.

### 5.3 Review

A person checks the content and records the check.

The production doctrine is that a human pass is the only thing that makes a
row servable, and the notes say plainly that if the serving app ever owns
human verification writes, that is a new capability with its own design. It
does not, so the review step belongs to the bank.

The review step has to produce a verification row the server's predicate
accepts, which means four things at once. The kind is `human`. The verdict is
`pass` or `fail`. The scope covers both `answer` and `explanation`, because
a pass that covers only the answer does not serve the row. And the
`content_hash` is the hash of the content as it stands at the moment of the
check, so the check cannot be applied to content that has since changed.

The bank's own AI checks write `ai_bulk` or `ai_single` rows. They are
evidence for the reviewer and they are never the thing that makes a row
servable. A bulk run and a single careful check are different evidence, and
the kind field is where that difference lives.

### 5.4 Promote

Move approved content into the tables the server reads.

Promotion has three obligations, and they are the whole reason the boundary
exists.

1. **The shape.** The tables must match `READ_SHAPES`, because the server
   fails closed when a column is missing.
2. **The version.** Promotion stamps `meta.contract_version` with the value
   the promoted content was built against.
3. **The hash.** Every promoted row carries the hash its verification
   covered. A row whose hash drifts from its verification falls out of
   service on the next read, which is the mechanism working, not failing.

Promotion is the one step that needs a person, and it is the step the
earlier scope excluded. The design keeps it, because a pipeline without it has
nowhere to send its work, but the mechanics of the human sign-off are a
separate decision.

---

## 6. The way back in

### 6.1 Reports

The server owns a `reports` table with a target-agnostic shape:

```sql
CREATE TABLE reports (
    id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
    reporter TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE(reporter, target_type, target_id, reason)
);
```

A report is a claim that something in the bank is wrong. Five reasons, and a
report can target any type, not only a question.

The bank should consume reports and turn them into work. A report against a
row the bank promoted means either the content is wrong, which the bank can
fix and re-promote, or the report is wrong, which the bank records and drops.
That judgement belongs to a person, and the bank's job is to present it
cleanly.

### 6.2 Drift

The server already detects drift. A row's stored `content_hash` is compared
to the hash its verification covered, and a mismatch drops the row out of
service until someone verifies it again.

The bank should run the same comparison against the rows it promoted, so a
row that changed comes back as work rather than as a silent loss of coverage.
The comparison is cheap, and the bank holds the promoted set, so it is the
only place the check can run against both sides at once.

---

## 7. What the bank never does

- **Never serves.** The server serves, from a replica.
- **Never writes a bank row into the server's database directly.** It
  promotes into Turso, and the server pulls.
- **Never writes a `human` verification.** A person does, and the person is
  the bank's review step.
- **Never creates an API-owned table.** The five operational tables are the
  server's.
- **Never guesses.** The figure position is data. A topic placement comes
  from the catalog, and the catalog is the server's table, created by the
  bank and shared.
- **Never drops a refusal.** Every rule that says no says why, and the count
  is reported.

---

## 8. Where the code stands against this

### 8.1 Already right

- **The ports.** `Source`, `ImageDescriber`, `Explainer`, `Tagger`,
  `AnswerVerifier`, `CatalogReader`, `MediaStore`, `StagingStore`,
  `MediaFetcher`, `MediaValidator`.
- **The catalog is read, not copied.** The catalog reader queries the
  server's `subjects`, `topics` and `subtopics`.
- **The mark shape and the fingerprint.** Both match production exactly, the
  fingerprint verified against all 2,243 production rows.
- **The media store** is content addressed, keyed by the sha256 of the bytes.
- **The state machine's spine**, from `planned` to `ready`, maps onto the
  four jobs.

### 8.2 Wrong today

| What | Should be |
|---|---|
| The mark list key is `marks` | `inline`, the key the server reads and serves |
| The passage is nested inside the question | its own row in a `passages` table, with a kind and a title, and questions pointing at it by id |
| The bank has no gate | the gate is the main product, and the `gated` state has nothing behind it |
| The bank has no dedupe | `deduped` has nothing behind it either, and dedupe has to compare against the server's stored hashes, not only against the bank's own rows |
| The bank never reads the server's `verifications` | it should, to know what has already been checked |
| The bank never reads the server's `reports` | a report is work, and the table is right there |
| There is no `live` state and no `reported` state | a promoted item has to stay tracked, and a report has to become work |
| Nothing checks for drift | the server's own predicate detects it, and the bank should run the same check against what it promoted |
| The bank treats the server's tables as its own | the bank creates the sixteen content tables and leaves the five operational ones alone |
| The bank has no notion of `contract_version` | promotion stamps it |

### 8.3 There, but empty

Two models exist with no implementation behind them, and both are central.

**`GateVerdict`.** It carries `passed`, a list of `Issue` with a severity, and
a rules version. That is the right shape for the gate's answer. No code
produces it, so nothing can fail yet.

**The `verifications` list on `Evidence`.** It carries a kind, a verdict, a
scope, a content hash, a reviewer, a note and a producer. The server's row
has `auto_rule`, `ai_bulk`, `ai_single` and `human`, and the bank's `ai`
collapses the two AI kinds into one. A bulk run and a single careful check
are different evidence.

### 8.4 The order that makes sense

1. **The gate.** It is the main product, it is well specified in 5.2, and
   the model for its answer already exists. Everything after it assumes the
   gate can say no.
2. **The passage as its own row**, with a `passages` table in the bank and a
   `passage_id` on the question.
3. **The key rename to `inline`,** which makes a staged payload promotable
   without a translation step.
4. **Dedupe**, against the server's stored `content_hash` and against the
   bank's own rows.
5. **Promotion**, with the shape check and the `contract_version` stamp.
6. **The `live` state and the drift check,** so a promoted item stays
   tracked.
7. **The report consumer,** so a consumer's complaint becomes work.

The media work waits. The source url on the mark renders today, and the asset
pipeline is a later cleanup rather than a blocker for any of the seven above.

---

## 9. Sources

| What | Where |
|---|---|
| The current production types | `src/core/models/domain.rs` |
| The wire shapes | `src/core/models/wire.rs` |
| The read dependency list and the contract check | `src/store/schema.rs` |
| The bank DDL | `src/testing.rs`, `BANK_DDL` |
| The serving predicate | `src/store/catalog.rs`, `verified_predicate` and `LATEST_VERIFIED_CTE` |
| The replica lifecycle | `src/store/sync.rs` |
| The pipeline doctrine | `docs/NOTES.temp.md` |
| The archived tree, a source of capabilities and never of structure | `utmelab-api-old/` |
| The decision log, the rich text rule and the figure rules | `utmelab-api-old/docs/` |
| The live database | the Turso production database |
