# How utmelab-bank is supposed to be

Written 2026-10-21. Built from the live production database, the current
production source in this repository, the live tooling in `tools/`, and the
pipeline notes in `docs/NOTES.temp.md`.

This document says what the bank should look like. It is not a report on what
the code does today. The gap between the two is in section 11.

Everything here was measured or read on 2026-10-21. Numbers are from the live
database, and the queries that produced them are named where the number
matters.

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

The bank is on the pipeline side of that line. It creates the sixteen, and it
creates their indexes.

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

**The live DDL is the specification, not the test DDL.** The server's own
test fixtures build the bank tables from `BANK_DDL` in `src/testing.rs`, and
that DDL is deliberately loose: no primary keys, no `NOT NULL` constraints,
and no `text_norm` column. It exists so a test can insert a partial row. The
live tables are the real thing, and the bank should create them as they are.
Section 3 has the live DDL.

**The columns the server does not read.** `questions.text_norm` exists in the
live table and the server does not read it. It is a leftover from the old
tree. The bank should still write it, and section 4.6 says why.

**The fingerprint is the pipeline's job.** The server never computes a content
hash. It reads the one stored on the row and compares it to the one stored on
the verification. If those two differ, the row is not servable. So the
algorithm lives entirely on the bank's side of the line, and it has to stay
byte for byte what the stored hashes already are, or every existing row falls
out of service the moment its content is touched.

Three implementations agree on this today. Production's stored hashes,
`tools/review.py`'s `content_fingerprint`, and the bank's own
`domain/hashing.py` produce the same value for all 2,243 live rows. That
three-way agreement is the thing to preserve.

---

## 3. The tables the bank owns

This is the live DDL, read from the production database on 2026-10-21. The
column list, the types, the primary keys and the nullability are all part of
the contract.

```sql
CREATE TABLE questions (
    id TEXT PRIMARY KEY, exam TEXT NOT NULL, subject TEXT NOT NULL,
    year INTEGER NOT NULL, source TEXT NOT NULL, text TEXT NOT NULL,
    inline TEXT NOT NULL DEFAULT '[]', options TEXT NOT NULL,
    answer TEXT NOT NULL, subtopic_id TEXT, section TEXT, passage_id TEXT,
    explanation TEXT, marks REAL NOT NULL, difficulty INTEGER NOT NULL,
    content_hash TEXT NOT NULL, text_norm TEXT NOT NULL DEFAULT ''
);

CREATE TABLE verifications (
    id TEXT NOT NULL, question_id TEXT NOT NULL, kind TEXT NOT NULL,
    verdict TEXT NOT NULL, scope TEXT NOT NULL DEFAULT '[]',
    verifier TEXT NOT NULL, detail TEXT, content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_ver_q ON verifications (question_id, created_at);

CREATE TABLE passages (
    id TEXT PRIMARY KEY, exam TEXT NOT NULL, subject TEXT NOT NULL,
    year INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT, author TEXT,
    text TEXT NOT NULL, inline TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE subjects (
    slug TEXT NOT NULL, exam TEXT NOT NULL, name TEXT NOT NULL,
    is_compulsory INTEGER NOT NULL, objective_paper_questions INTEGER,
    PRIMARY KEY (slug, exam)
);

CREATE TABLE topics (
    slug TEXT PRIMARY KEY, subject TEXT NOT NULL, exam TEXT NOT NULL,
    name TEXT NOT NULL, "order" INTEGER NOT NULL, weight INTEGER NOT NULL DEFAULT 0,
    objectives TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE subtopics (
    slug TEXT PRIMARY KEY, topic TEXT NOT NULL, name TEXT NOT NULL,
    "order" INTEGER NOT NULL, objectives TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE exams (
    code TEXT PRIMARY KEY, name TEXT NOT NULL, countries TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL, has_full_paper INTEGER, subjects_required INTEGER,
    duration_minutes INTEGER, rules TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE exam_requirements (
    exam TEXT NOT NULL, country TEXT NOT NULL, "group" TEXT NOT NULL,
    min_select INTEGER NOT NULL, subjects TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE countries (code TEXT PRIMARY KEY, name TEXT NOT NULL);

CREATE TABLE topic_countries (
    topic TEXT NOT NULL, country TEXT NOT NULL, PRIMARY KEY (topic, country)
);

CREATE TABLE blueprints (
    exam TEXT NOT NULL, subject TEXT NOT NULL, level TEXT NOT NULL,
    topic TEXT, section TEXT, members TEXT NOT NULL DEFAULT '[]',
    paper_size INTEGER NOT NULL, pct REAL, pct_low REAL, pct_high REAL,
    expected REAL, expected_low REAL, expected_high REAL,
    source TEXT, sample TEXT, method TEXT NOT NULL, confidence TEXT,
    status TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE novels (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL,
    year_published INTEGER, exam TEXT NOT NULL, year_prescribed TEXT NOT NULL DEFAULT '[]',
    category TEXT NOT NULL DEFAULT 'english', featured INTEGER NOT NULL DEFAULT 0,
    synopsis TEXT NOT NULL, setting_place TEXT NOT NULL,
    setting_period TEXT NOT NULL, cover_image TEXT
);

CREATE TABLE novel_chapters (
    novel_id TEXT NOT NULL, number INTEGER NOT NULL, title TEXT NOT NULL,
    summary TEXT, key_events TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (novel_id, number)
);

CREATE TABLE novel_characters (
    novel_id TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
    character_type TEXT NOT NULL, description TEXT NOT NULL,
    PRIMARY KEY (novel_id, name)
);

CREATE TABLE novel_themes (
    novel_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '[]', PRIMARY KEY (novel_id, name)
);

CREATE TABLE novel_questions (
    id TEXT PRIMARY KEY, novel_id TEXT NOT NULL, chapter_number INTEGER,
    text TEXT NOT NULL, inline TEXT NOT NULL DEFAULT '[]', options TEXT NOT NULL,
    answer TEXT NOT NULL, explanation TEXT, content_hash TEXT NOT NULL
);
```

### 3.1 The indexes the pipeline must create

The live `questions` table carries five indexes. They are the pipeline's, not
the server's, and the pipeline has to create them.

```sql
CREATE INDEX idx_q_exam_subject ON questions (exam, subject);
CREATE INDEX idx_q_subtopic     ON questions (subtopic_id);
CREATE INDEX idx_q_source       ON questions (source);
CREATE INDEX idx_q_year         ON questions (year);
CREATE INDEX idx_q_text_norm    ON questions (text_norm);
CREATE INDEX idx_ver_q          ON verifications (question_id, created_at);
```

**One index is missing and the bank needs it.** There is no index on
`questions.content_hash`. A lookup by hash is a full table scan, measured at
0.081 s against 112,150 rows locally, and the bank's dedupe step is a hash
lookup per candidate. Adding the index took that same lookup to 0.000 s.

```sql
CREATE INDEX idx_q_hash ON questions (content_hash);
```

**One index is missing and the server would like it.** The server's public
aggregate query scans the whole `verifications` table. Section 9 has the
measurements.

```sql
CREATE INDEX idx_ver_kind ON verifications (kind, question_id, created_at DESC, id DESC);
```

### 3.2 What is not there

No media table. No assets table. No image column. A figure is a mark.

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

**The key is `inline`.** The live `tools/review.py` reads the JSON bank with
`q["text"]["inline"]` and writes its verification rows against that shape, so
the bank's payload key has to be `inline` for the two to meet. The mark list
inside is already identical to production's, but the key is not, and a
payload the bank cannot hand to the existing tool is a payload that is not
promotable.

Two rules on the marks. Offsets count Unicode scalar values, never bytes, so
a character outside the basic plane still counts as one. And two marks may
share an identical range, bold on top of underline is the case the old
decision log names, while a partial overlap is refused.

### 4.2 The question row

The 17 columns of `questions` and what the bank puts in each.

| Column | What goes in it |
|---|---|
| `id` | The identity. The primary key, so an id is used once. |
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
| `text_norm` | The full-Unicode lowercase of the stem. See 4.6. |

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
the schema and unused.

**The bank's own checks stay in the bank.** The server filters on
`v.kind = 'human'` before it does anything else, so a non-human row can never
change a served answer. But the filter is applied by scanning, and the scan
is over the whole table. Writing the bank's AI evidence into production's
`verifications` table would grow the table that every public request scans,
for rows that can never affect the answer. So: production's table holds human
verifications, and the bank's AI evidence lives in the bank's own store. That
is a scale decision with a correctness reason behind it.

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

28 questions point at a passage, and one passage serves up to 9 questions.
Every question that points at a passage shares its subject, without exception.

| Passage | Kind | Title | Questions |
|---|---|---|---|
| `psg_jamb_2025_eng_cloze_3` | Cloze | Passage C | 9 |
| `psg_jamb_2025_eng_comprehension_1` | Comprehension | Passage A | 5 |
| `psg_jamb_2025_eng_birds_1` | Comprehension | Bird calls | 5 |
| `psg_jamb_2025_eng_comprehension_2` | Comprehension | Passage C | 3 |
| `psg_jamb_2025_eng_cloze_2` | Cloze | Passage D | 3 |
| `psg_jamb_2025_eng_reading_1` | ReadingText | The Lekki Headmaster | 1 |
| `psg_jamb_2025_eng_cloze_1` | Cloze | Passage B | 1 |
| `psg_jamb_2025_commerce_data_1` | Data | Working capital data | 1 |

`kind` is not decoration. It tells the consumer how to read the passage. A
cloze carries its gaps in the plain text as four dots, and that is data, not
markup. A data passage is numbers, and the question against it asks for a
figure.

So the bank holds a passage as its own row, and a question that references it
by id. Nesting the passage inside the question is wrong on both counts. It
forbids two questions sharing one passage, which production does 28 times,
and it has nowhere to put `kind`.

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

### 4.6 text_norm, and the SQLite lower trap

`text_norm` is the **full-Unicode** lowercase of the stem. Python's
`.lower()` and Rust's `.to_lowercase()` produce it.

SQLite's built-in `lower()` is **ASCII only**. 41 live rows prove the
difference, and they are not rare rows:

```
text: '2SO\(_2\)\(_{(s)}\) + O\(_2\)\(_{(s)}\) ⇌ 2SO\(_3\) ; ΔG° = - ve ...'
norm: '2so\(_2\)\(_{(s)}\) + o\(_2\)\(_{(s)}\) ⇌ 2so\(_3\) ; δg° = - ve ...'
```

The `Δ` became `δ` in the stored value. SQLite's `lower()` would have left
the `Δ` alone, so `text_norm != lower(text)` for every row with a non-ASCII
character, and those are the Hausa, Igbo, Yoruba, Arabic and chemistry rows.

Two rules follow.

1. **The bank writes `text_norm` with Python's `.lower()`**, never with a
   SQL `lower()`. Python's matches the stored values on all 2,243 rows.
2. **The bank never dedupes in SQL with `lower(text)`.** It compares the
   `text_norm` column, which is indexed, and which is the full-Unicode
   value. A SQL dedupe on `lower(text)` would miss every non-ASCII row and
   disagree with the index.

The server does not read `text_norm` today, and its `?q=` search is a
`LIKE` on `text`. The column and its index are still worth keeping, because
the bank needs an exact, indexed, case-folded key, and because the live table
has the column and a fresh table should not differ from the live one.

---

## 5. The trust boundary

**The server does not validate rows.** This is the most important fact in
this document, and it decides how much weight the gate carries.

`src/store/catalog.rs` reads a question with `map_question`, which
deserializes the JSON columns and type-checks the scalars. It does not check
that a mark fits inside its text, that the answer names an option, that the
options number four, that the subtopic exists, or that the text carries no
markup. There is no `validate` on a row anywhere in the current source. The
only `validate` functions are for the config and for identifier sanitisation.

The server's own test says what happens when a row is malformed:

```rust
async fn get_question_rejects_bad_option_json() {
    // ... INSERT INTO questions VALUES ('bad', ..., 'not-json', ...)
    let err = get_question(&s, "bad").await.expect_err("malformed options fail loudly");
    assert!(matches!(err, crate::error::AppError::Upstream(_)));
}
```

So a single bad row promoted into production does one of two things.

**It breaks the endpoint for every consumer.** A row whose `options` is not
valid JSON, or whose `inline` is not an array, or whose `year` does not fit
in a `u16`, or whose `marks` is not a number, makes the whole list read fail.
Not that one row. The whole read, and therefore the whole endpoint.

**Or it is served as wrong content.** A mark that runs past the end of its
text, an answer that names no option, a question with six options, a stem
carrying HTML, a subtopic that does not exist. The server reads these
perfectly happily and hands them to a student.

There is no second line of defence. The gate is the only defence, and it is
the bank's. The archived tree's `RichText::validate` and `quarantine.rs`
existed because the bank was the only place that could say no. The current
code has dropped those checks because the pipeline owns validation now, and
that is exactly why the pipeline's gate has to be stronger, not weaker.

Every rule in section 6 exists to stop one of those two outcomes.

---

## 6. The four jobs

### 6.1 Intake

Take content from a source and put it in the bank's shape, without judging
it yet.

The bank should be able to take content from several kinds of source,
because the production tooling shows the range: harvested pages, syllabus
files, an inbox of claims, and passages recovered from papers. The bank's
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

### 6.2 Gates

The gate is the bank's main product. The production notes are blunt about
where it belongs: the old tree's `import` and `quarantine` verbs are pipeline
work, and the bank's gate and review steps are their successors.

**The rules in force are the live ones in `tools/review.py`**, not the
archived Rust's import rules. The live tool is what writes today's
verification rows, so its rules are the ones a new row has to pass.

The tool's own summary says what it is for: "the machine checks what it can".
It has two halves. The quarantine flags, which are computed for every row and
listed, and the refusals, which stop a write.

The flags, and what they say about the live bank:

| Flag | Rule | Live rows flagged |
|---|---|---|
| `underline_missing` | the stem mentions "underlin" and carries no underline mark | 0 |
| `missing_figure` | the stem mentions a figure and carries no image mark | 2 |
| `option_count` | the question does not have exactly 4 options | 11 |
| `novel_leak` | the stem or an option carries novel content ("bepo", "stardom", "lekki") | 0 |
| `cloze_without_passage` | the stem has a numbered gap and no `passage_id` | 0 |
| `duplicate_stem` | a near-duplicate of another row | 0 |

The refusals, which stop the write:

| Refusal | Rule |
|---|---|
| `Resolve first: <flags>` | a quarantined row cannot be verified, so it cannot become servable |
| no explanation | a row with no explanation cannot be verified, because the pass has to cover the explanation |
| no such subtopic under this exam and subject | the subtopic must exist, and its topic must belong to the row's exam and subject |
| the underline is not a substring of the stem | an underline is a verbatim substring, and the offset is computed from it |
| marks outside 0.5 to 10.0 | the JAMB norm is 1.0 to 3.0 |
| difficulty outside 1 to 5 | |
| no such passage | a passage id must exist |

Two details in there are worth keeping exactly.

**The underline is a substring, not an offset.** The tool takes the target
text, finds it in the stem, and computes the span. One underline per stem is
the observed shape, so a new underline replaces any existing underline marks
rather than stacking on them. The bank should propose a substring and compute
the offsets, so a target that is not in the stem is caught before it becomes
an offset.

**The figure matcher is careful about word boundaries, and the care matters,
because the hint words collide with ordinary English.** Of the 2 live flags,
one is a true positive, the physics row about a "displacement-time graph",
and one is a false positive, a stress question whose last option is the word
"table". A rule that refused on the word "table" would have thrown away a
legitimate question, and would have thrown away more as the bank grows.

**So the figure rule flags, it does not refuse the row.** The archived tree
turned it into a refusal at import. The live tool's behaviour is the one in
force, and it is the safer one: the row is flagged, a person decides, and the
ordinary word does not cost the bank a question.

The near-duplicate fingerprint is not the content hash. It is the lowercased
stem plus the sorted lowercased option texts, hashed to 16 hex characters.
It catches a reworded duplicate that the exact hash would miss, and it is
what the live tool uses for the duplicate flag.

**The gate also owns the hash.** A gate that passes a row hands over a row
whose `content_hash` is correct, because the hash is the receipt every later
stage depends on.

**And the gate owns the exactness check against production.** A row whose
hash already exists in production is a duplicate, and a row whose id already
exists is a re-promotion. Both are counted, not silently overwritten.

### 6.3 Review

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

The bank's own AI checks write `ai_bulk` or `ai_single` rows into the bank's
own store. They are evidence for the reviewer and they are never the thing
that makes a row servable. A bulk run and a single careful check are
different evidence, and the kind field is where that difference lives.

### 6.4 Promote

Move approved content into the tables the server reads.

**No code in this repository does this today.** The archived tree's
`bank/write.rs` did. The live `tools/review.py` writes JSON files, not
rows. The promotion path is the bank's to build, and it is the last job
because it is the one that touches the served tables.

Promotion has five obligations.

1. **The shape.** The tables must match the live DDL in section 3, primary
   keys and `NOT NULL` constraints included, because the server fails closed
   when a column is missing and the metadata surface reads `SELECT *`.
2. **The indexes.** Section 3.1. They are the pipeline's to create.
3. **The version.** Promotion stamps `meta.contract_version` with the value
   the promoted content was built against.
4. **The hash.** Every promoted row carries the hash its verification
   covered. A row whose hash drifts from its verification falls out of
   service on the next read, which is the mechanism working, not failing.
5. **Idempotence.** Promotion is an upsert by id, and it is safe to run
   twice. A re-run must not change a row's content, because a changed
   content changes the hash, and a changed hash voids the verification that
   made the row servable.
6. **Read back or roll back.** The live tool already does this for the JSON
   bank: copy the file to a backup, write, re-read it, and if it cannot be
   parsed back, restore the backup and stop. Promotion does the same against
   the database: write, read the row back, compare the hash to the one the
   verification covered, and if they differ, roll the write back. A write
   that cannot be read back is not shipped.

Promotion is the one step that needs a person, and it is the step the
earlier scope excluded. The design keeps it, because a pipeline without it
has nowhere to send its work, but the mechanics of the human sign-off are a
separate decision.

---

## 7. The way back in

### 7.1 Reports

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
report can target any type, not only a question. The table holds 1 row
today.

The bank should consume reports and turn them into work. A report against a
row the bank promoted means either the content is wrong, which the bank can
fix and re-promote, or the report is wrong, which the bank records and drops.
That judgement belongs to a person, and the bank's job is to present it
cleanly.

### 7.2 Drift

The server already detects drift. A row's stored `content_hash` is compared
to the hash its verification covered, and a mismatch drops the row out of
service until someone verifies it again. 50 live rows are in that state right
now, which is the mechanism working: their content moved on and no one
re-verified them.

The full servable count is 2,189 of 2,243, and the 54 excluded rows break
down exactly.

| Rows | Why they are not servable |
|---|---|
| 50 | No explanation. The review step refuses to verify a row with no explanation, so these were never verified and their hash matches nothing. |
| 1 | `exam` is empty, so the row is withheld. |
| 2 | No subtopic, so the row is not attributable to a topic. These are also among the 50 with no explanation. |
| 1 | No subtopic, but it does carry a matching verification hash. Unattributable, but verified. |

2,243 minus 50 minus 1 minus 3 is 2,189, so nothing else is filtering
anything out. The 50 rows with no explanation and the 53 rows with no
matching verification hash are the same set apart from 3, and that is the
mechanism working: a row that was never explained was never verified, so it
was never servable.

The bank should run the same comparison against the rows it promoted, so a
row that changed comes back as work rather than as a silent loss of coverage.
The comparison is cheap, and the bank holds the promoted set, so it is the
only place the check can run against both sides at once.

---

## 8. What the bank never does

- **Never serves.** The server serves, from a replica.
- **Never writes a bank row into the server's database directly.** It
  promotes into Turso, and the server pulls.
- **Never writes a `human` verification.** A person does, and the person is
  the bank's review step.
- **Never creates an API-owned table.** The five operational tables are the
  server's.
- **Never guesses.** The figure position is data. A topic placement comes
  from the catalog, and the catalog is a table the bank creates and the
  server reads.
- **Never drops a refusal.** Every rule that says no says why, and the count
  is reported.
- **Never promotes a row the gate has not passed.** The server will not catch
  it, and one bad row breaks an endpoint for everyone.

---

## 9. Scale

The bank is going to handle a lot of questions, so the shapes have to hold up
when the table is big. These are measurements, not projections.

### 9.1 The public aggregate query is linear in verifications

`/api/v1/public/exams` and `/api/v1/public/summary` are keyless. They run
one windowed pass over `verifications` and join it to `questions`. The plan,
read from the live replica:

```
SCAN verifications AS v
SCAN json_each          (twice, once per scope check)
USE SORTER FOR ORDER BY
```

The pass is `ROW_NUMBER() OVER (PARTITION BY question_id ORDER BY created_at DESC, id DESC)`,
and the scope check is `json_each`, a table-valued function, evaluated once
per candidate verification row.

Measured on the live remote at 2,268 verifications: **0.75 s** for
`public_exams`, 0.79 s for `subject_stats`. On an unauthenticated route.

Measured on a local replica of the same data and the same queries, so the
shape is visible without the network:

| Population | `public_exams` | `subject_stats` |
|---|---|---|
| 2,243 questions, 2,268 verifications | 0.038 s | 0.037 s |
| 22,430 questions, 22,680 verifications | 0.461 s | 0.432 s |
| 112,150 questions, 113,400 verifications | 2.046 s | 2.058 s |

Linear in the verifications, and the remote engine is about 19 times slower
than local sqlite on the same data, so the remote at 112,000 verifications
would be tens of seconds on a keyless route.

**The index that fixes it** is the one in section 3.1:

```sql
CREATE INDEX idx_ver_kind ON verifications (kind, question_id, created_at DESC, id DESC);
```

With it, the plan changes `SCAN verifications` to
`SEARCH v USING INDEX idx_ver_kind (kind=?)`, and the sorter disappears.

**The rule for the bank** follows from it. Production's `verifications` table
holds human verifications and nothing else. The bank's AI evidence stays in
the bank. Every AI row written into production's table would be a row the
public route has to scan, for a row that can never change a served answer.

### 9.2 Dedupe needs the hash index

The bank's dedupe step is a hash lookup per candidate row. Without an index
on `questions.content_hash` that is a full table scan.

Measured locally at 112,150 rows: **0.081 s** without the index, **0.000 s**
with it. The bank creates the index, so this is the bank's decision to make
and it is not a close call.

### 9.3 The text search is a full scan

The server's `?q=` filter is `text LIKE '%q%' ESCAPE '\'`, a leading
wildcard, so no index can serve it, and `idx_q_text_norm` is not used by the
current code. It is a scan of the questions table on every searching
request. That is the server's cost, not the bank's, and the bank cannot
change it, but the bank should know that a big bank makes it worse.

### 9.4 What the bank controls

The bank controls how fast `questions` and `verifications` grow. That is the
whole of the server's query cost. Three levers, in order of effect:

1. **Keep non-human verifications out of production's table.** The server
   filters on `kind='human'` but scans first.
2. **Promote only what the gate passed and a person verified.** A row that is
   promoted without a human pass is a row that costs a scan and serves
   nothing.
3. **Keep the content hash exact.** One exact hash per distinct question,
   with the index, makes dedupe an O(1) lookup instead of a comparison
   against the whole bank.

---

## 10. What the bank produces

A promotable item is a `questions` row plus, where the question needs one, a
`passages` row. Nothing else changes.

| Produced | Shape |
|---|---|
| A question | The 17 columns above, with `content_hash` and `text_norm` computed by the bank. |
| A passage | The 9 columns above, when the question points at one. |
| A verification | `kind`, `verdict`, `scope`, `verifier`, `detail`, `content_hash`, `created_at`. The bank writes `ai_bulk` and `ai_single` into its own store. A person writes `human` into production's. |
| A media url | The bank's own url for a stored asset, in place of the source url, once the asset exists. |

Everything else in production's tables is read only for the bank: the
catalog, the blueprints, the countries, the exam requirements.

---

## 11. Where the code stands against this

### 11.1 Already right

- **The ports.** `Source`, `ImageDescriber`, `Explainer`, `Tagger`,
  `AnswerVerifier`, `CatalogReader`, `MediaStore`, `StagingStore`,
  `MediaFetcher`, `MediaValidator`.
- **The catalog is read, not copied.** The catalog reader queries the
  server's `subjects`, `topics` and `subtopics`.
- **The mark shape and the fingerprint.** Both match production exactly, the
  fingerprint verified three ways on all 2,243 production rows: production's
  stored hash, `tools/review.py`, and the bank.
- **The media store** is content addressed, keyed by the sha256 of the bytes.
- **The state machine's spine**, from `planned` to `ready`, maps onto the
  four jobs.

### 11.2 Wrong today

| What | Should be |
|---|---|
| The mark list key is `marks` | `inline`, the key the server reads and the live tooling writes |
| The passage is nested inside the question | its own row in a `passages` table, with a kind and a title, and questions pointing at it by id |
| The bank has no gate | the gate is the main product, and the `gated` state has nothing behind it |
| The bank has no dedupe | `deduped` has nothing behind it either, and dedupe has to compare against the server's stored hashes, not only against the bank's own rows |
| The bank never reads the server's `verifications` | it should, to know what has already been checked |
| The bank never reads the server's `reports` | a report is work, and the table is right there |
| There is no `live` state and no `reported` state | a promoted item has to stay tracked, and a report has to become work |
| Nothing checks for drift | the server's own predicate detects it, and the bank should run the same check against what it promoted |
| The bank treats the server's tables as its own | the bank creates the sixteen content tables and their indexes, and leaves the five operational ones alone |
| The bank has no notion of `contract_version` | promotion stamps it |
| The bank has no promotion writer at all | the archived tree had one, and the live tooling writes JSON files, so the path does not exist |

### 11.3 There, but empty

Two models exist with no implementation behind them, and both are central.

**`GateVerdict`.** It carries `passed`, a list of `Issue` with a severity, and
a rules version. That is the right shape for the gate's answer. No code
produces it, so nothing can fail yet.

**The `verifications` list on `Evidence`.** It carries a kind, a verdict, a
scope, a content hash, a reviewer, a note and a producer. The server's row
has `auto_rule`, `ai_bulk`, `ai_single` and `human`, and the bank's `ai`
collapses the two AI kinds into one. A bulk run and a single careful check
are different evidence.

### 11.4 The order that makes sense

1. **The gate.** It is the main product, it is specified in 6.2, and the
   model for its answer already exists. Everything after it assumes the gate
   can say no.
2. **The passage as its own row**, with a `passages` table in the bank and a
   `passage_id` on the question.
3. **The key rename to `inline`,** which makes a staged payload promotable
   without a translation step, and matchable by the live tooling.
4. **Dedupe**, on the exact hash, against the server's stored hashes and
   against the bank's own rows, with the hash index in place.
5. **Promotion**, with the shape, the indexes and the `contract_version`
   stamp.
6. **The `live` state and the drift check,** so a promoted item stays
   tracked.
7. **The report consumer,** so a consumer's complaint becomes work.

The media work waits. The source url on the mark renders today, and the asset
pipeline is a later cleanup rather than a blocker for any of the seven above.

---

## 12. Sources

| What | Where |
|---|---|
| The current production types | `src/core/models/domain.rs` |
| The wire shapes | `src/core/models/wire.rs` |
| The read dependency list and the contract check | `src/store/schema.rs` |
| The live DDL | the production database, read on 2026-10-21 |
| The loose test DDL, not the spec | `src/testing.rs`, `BANK_DDL` |
| The serving predicate and the row readers | `src/store/catalog.rs` |
| The replica lifecycle | `src/store/sync.rs` |
| The pipeline doctrine | `docs/NOTES.temp.md` |
| The live gate rules and the fingerprint | `tools/review.py` |
| The archived tree, a source of capabilities and never of structure | `utmelab-api-old/` |
| The decision log, the rich text rule and the figure rules | `utmelab-api-old/docs/` |
