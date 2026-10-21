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

**utmelab-bank is a content factory.** Its job is to produce exam questions
that are ready to be served. That is the whole concern.

The API is the customer. It serves questions, and a served API with no
questions serves nothing. So the stage we are at is filling the bank, and the
measure of success is content that is complete, correct, placed, and reviewed.

**The Rust is not ours.** We read it to learn the shape the content has to
take, and that is all. It is also an MVP in progress, built so it can serve
while the work continues. So its internals are a moving target, and the
design deliberately does not hang on them. What the content must look like is
the stable part, and the content is what we build.

**Promotion is not ours either.** How a ready row reaches the production
database, and who puts it there, is a separate piece of work. The bank stops
at ready. Everything a bundle needs to be mechanically placeable is
therefore part of the bank's job, and the act of placing it is not.

That leaves three jobs, and the fourth is the output.

| Job | What it does |
|---|---|
| **Intake** | Take content from a source and put it in the canonical shape, without judging it yet. |
| **Gates** | Decide whether that content is sound, and say why when it is not. |
| **Review** | Have a person check the content and record the check. |
| **Ready** | The output. A bundle that is complete, correct, placed and reviewed, so that placing it is a mechanical step. |

The production notes name the same set of words, and call the fourth "promote",
because the archived tree did the placing too. We do not.

```
   sources                    utmelab-bank                    ready content
   ───────                    ────────────                    ─────────────
   harvest ─┐
   syllabus ─┼─▶ intake ─▶ gates ─▶ review ─▶ ready ─▶ a bundle a person
   inbox   ─┘                                         can place with no
                                                      judgement left to do
```

### 1.1 What production already has, and what it expects

One Turso database holds the served content and the API's own operational
tables. The split is by ownership.

| Owner | Tables |
|---|---|
| **The API** | `meta`, `api_keys`, `dashboard_users`, `sessions`, `reports`. Five tables, all operational. |
| **The content** | `questions`, `verifications`, `passages`, `subjects`, `topics`, `subtopics`, `exams`, `exam_requirements`, `countries`, `topic_countries`, `blueprints`, `novels`, `novel_chapters`, `novel_characters`, `novel_themes`, `novel_questions`. Sixteen tables, all content. |

The catalog is the part of the content that the bank must place against. A
question without a subtopic is not attributable to anything, and 3 of the
2,243 live rows are in exactly that state, so the catalog is read and
respected, never invented.

The server checks its own tables against the shape it expects, and fails
closed when a table or a column is missing. The bank does not implement that
check, and does not need to. It needs to produce content that matches the
shape in section 3, so that whoever places it does not have to reshape
anything.

### 1.2 The shape of the content is the stable part

The server's internals will move. The following will not, because they are
properties of the content rather than of a program.

- A question is a stem, some options, an answer that names one of them, and
  optionally an explanation.
- Every text-bearing thing is the same shape, so a consumer that learned one
  has learned all of them.
- A question's identity is its content, so a change to the content is a
  change of identity, and any check made about the old content no longer
  applies.
- A question belongs to a topic, and the topic is named by the catalog.
- A question that cannot be answered without a stimulus carries the id of
  that stimulus.

Those five are the design. The column names and the JSON keys are the shape
that carries them today.

---

## 2. The content model

### 2.1 One RichText, everywhere

`src/core/models/domain.rs` is the current specification, and it says the
quiet part out loud:

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

**The key is `inline`.** The live `tools/review.py` reads the content with
`q["text"]["inline"]`, and the live JSON bank uses that shape, so the bank's
payload has to use it too. The mark list inside is already identical to
production's, but the key is not, and a payload the bank cannot hand to the
existing tooling is a payload that is not ready.

Two rules on the inlines. Offsets count Unicode scalar values, never bytes, so
a character outside the basic plane still counts as one. And two inlines may
share an identical range, bold on top of underline is the case the old
decision log names, while a partial overlap is refused.

### 2.2 The question row

The 17 columns the live `questions` table carries, read from the production
database on 2026-10-21. The column list, the types, the primary key and the
nullability are all part of the shape the content has to take.

| Column | What goes in it |
|---|---|
| `id` | The identity. The primary key, so an id is used once. |
| `exam` | Never empty. An empty exam means the row is withheld and not servable. |
| `subject` | Must exist in `subjects` for that exam. |
| `year` | The cohort the question is prepared for, not the year it was lifted from. 1900 to 2100. |
| `source` | `past_paper`, `claimed_paper`, `authored` or `imported`. |
| `text` | The stem's plain text. |
| `inline` | The stem's inlines, as a JSON array. |
| `options` | A JSON array of `{"id": "a", "text": {"text": ..., "inline": [...]}}`. |
| `answer` | An option id, never a label and never an index. |
| `subtopic_id` | A subtopic slug. Must exist in `subtopics`. |
| `section` | The paper section name. Free text. |
| `passage_id` | The id of a passage, or null. |
| `explanation` | `{"key_point": ..., "body": ..., "trap": ...}` or null. |
| `marks` | A number. 0.5 to 10, and 1.0 to 3.0 for JAMB. |
| `difficulty` | 1 to 5. |
| `content_hash` | Derived by the bank, never authored. |
| `text_norm` | The full-Unicode lowercase of the stem. See 2.6. |

The `options` and `explanation` columns hold nested objects with their own
`inline`, while `text` and `inline` are separate columns for the stem. That
asymmetry is the real shape and it is not a mistake. The stem is the thing
that gets searched, so it is split so the search can use a plain column.

### 2.3 The verification record

| Field | What goes in it |
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

**This record decides whether a question is servable.** The rule, spelled
once in `src/store/catalog.rs`:

> the newest human verification carrying both `answer` and `explanation` must
> be a pass whose `content_hash` still matches the row.

Three consequences the bank has to respect.

1. **A content edit voids the check.** The hash is the receipt, so the bank
   must recompute it on every change and must never present a row whose hash
   does not match the check that covers it.
2. **Only a human check counts.** An AI check is signal. It never makes a
   row servable, and the bank must never present an AI check as a human one.
3. **The scope matters.** A human pass that covers only the answer does not
   serve a question, because the explanation would be unverified.

Production holds 2,268 verifications, every one of them `human`, `pass`,
with the scope `["answer","explanation"]`. The other three kinds are
supported by the schema and unused.

**The bank's own AI evidence stays in the bank.** The server filters on
`kind = 'human'` before it does anything else, so an AI record can never
change a served answer. The bank's AI checks are evidence for the reviewer,
and they live in the bank's own store.

### 2.4 Passages

A passage is a stimulus a question depends on. The server's own comment on
the wire type says it plainly:

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

So the bank holds a passage as its own object with its own identity, and a
question that references it by id. Nesting the passage inside the question is
wrong on both counts. It forbids two questions sharing one passage, which
production does 28 times, and it has nowhere to put `kind`.

The bank's own shape, built:

| | The passage | The reference |
|---|---|---|
| Where it lives | the `passages` table, keyed by id | `content.passage_id` on the question |
| What it carries | id, exam, subject, year, kind, title, author, text | the id, and nothing else |
| Who shares it | any number of questions | |

The kind is a closed list of production's four: `Comprehension`, `Cloze`,
`ReadingText`, `Data`. A kind nobody can read is not a kind, so a new one is
a deliberate change.

Titles repeat. `Passage C` names two different production rows, one
Comprehension and one Cloze. The id is the only key.

### 2.5 Figures

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
pointing at `myschool.ng`. The bytes live on that site, and there is no media
table anywhere.

So the bank has two jobs around a figure, and the second one is not built
yet.

1. **The asset.** The bytes, their sha256, the mime type, the alt text, a
   description, and where they came from. The bank holds this, and there is
   no media table for it to live in.
2. **The swap.** Until the asset exists, the mark carries the source url, and
   that renders today. When the asset exists, the mark's url is replaced with
   the bank's own url for the stored asset.

The source url stays on the mark until the swap. A staged item always points
at something that renders.

### 2.6 text_norm, and the SQLite lower trap

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
2. **The bank never matches in SQL with `lower(text)`.** It compares the
   `text_norm` column, which is indexed, and which holds the full-Unicode
   value. A match on `lower(text)` would miss every non-ASCII row.

The server does not read `text_norm` today. The column is still worth
keeping, because the bank needs an exact, case-folded key for dedupe, and
because the live table has it.

### 2.7 The fingerprint

The bank computes a content hash for every question, and the hash is what
ties a review to the content it reviewed. The algorithm is fixed:

The parts, in order, joined by `U+001F`:

```
1  stem text
2  for each option:  "<option id>" + U+001E + "<option text>"
3  answer
4  inlines of the stem, then inlines of each option, each inline encoded as
   "<start>,<len>,<kind>", all joined by "|"
5  explanation key_point text
6  key_point inlines joined by "|"
7  explanation body text
8  body inlines joined by "|"
9  trap text, or "" when there is no explanation or no trap
10 trap inlines joined by "|"
```

A mark is encoded as `<start>,<len>,<kind>`, and an image mark is
`image:<url>:<position>:<alt>` with an empty alt when there is none. The
whole thing is sha256 of the parts joined by `U+001F`, hex encoded.

**The fingerprint does not cover the passage text, the media, the section or
the difficulty.** That is finding F18 in FINDINGS.md and it is still true of
production.

Three implementations agree on this today, on all 2,243 live rows:
production's stored hashes, `tools/review.py`'s `content_fingerprint`, and
the bank's own `domain/hashing.py`. That three-way agreement is the thing to
preserve, and the live contract test in `tests/live/` is what keeps it
honest.

---

## 3. The quality argument

**The content is the only place quality is enforced.** The server does no
semantic validation of a row. `src/store/catalog.rs` reads a question by
deserializing the JSON columns and type-checking the scalars. It does not
check that a mark fits inside its text, that the answer names an option, that
the options number four, that the subtopic exists, or that the text carries
no markup. There is no `validate` on a row anywhere in the current source.

The server's own test says what happens when a row is malformed:

```rust
async fn get_question_rejects_bad_option_json() {
    // ... INSERT INTO questions VALUES ('bad', ..., 'not-json', ...)
    let err = get_question(&s, "bad").await.expect_err("malformed options fail loudly");
    assert!(matches!(err, crate::error::AppError::Upstream(_)));
}
```

So one bad row either breaks the endpoint for every consumer, or is served as
wrong content. Both are the bank's problem, because the bank made the row.

This is why the archived tree had a `RichText::validate` and a
`quarantine.rs`, and why the current code can drop them: the checks moved to
the content side, so they have to move with it.

Every rule in section 4 exists to stop one of those two outcomes. The gate is
not a formality. It is the whole quality story.

---

## 4. The jobs

### 4.1 Intake

Take content from a source and put it in the canonical shape, without judging
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
puts it in the canonical shape and lets the gate decide, so the refusal is
counted and attributed rather than lost in a scraper.

### 4.2 Gates

The gate is the bank's main product. The production notes are blunt about
where it belongs: the old tree's `import` and `quarantine` verbs are pipeline
work, and the bank's gate and review steps are their successors.

**The rules in force are the live ones in `tools/review.py`**, not the
archived Rust's import rules. The live tool is what writes today's
verification records, so its rules are the ones a new row has to pass.

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
| `Resolve first: <flags>` | a quarantined row cannot be reviewed, so it cannot become servable |
| no explanation | a row with no explanation cannot be reviewed, because the pass has to cover the explanation |
| no such subtopic under this exam and subject | the subtopic must exist, and its topic must belong to the row's exam and subject |
| the underline is not a substring of the stem | an underline is a verbatim substring, and the offset is computed from it |
| marks outside 0.5 to 10.0 | the JAMB norm is 1.0 to 3.0 |
| difficulty outside 1 to 5 | |
| no such passage | a passage id must exist |

**Every refusal goes to the same person.** The gate refuses, and the person
either fixes the content or records a clearance with a reason. One queue, one
mechanism. The severity stays on the issue, so the counts still say what was
objectively broken and what needed judgement, but nothing leaves the bank
without a person having looked at it.

**The clearance is recorded, never silent.** It names the rule, the person
and the reason, so the decision survives the row.

Two details in there are worth keeping exactly.

**The underline is a substring, not an offset.** The tool takes the target
text, finds it in the stem, and computes the span. One underline per stem is
the observed shape, so a new underline replaces any existing underline inlines
rather than stacking on them. The bank should propose a substring and compute
the offsets, so a target that is not in the stem is caught before it becomes
an offset.

**The figure matcher is careful about word boundaries, and the care matters,
because the hint words collide with ordinary English.** Of the 2 live flags,
one is a true positive, the physics row about a "displacement-time graph",
and one is a false positive, a stress question whose last option is the word
"table". The rule still fires on the word "table", because a rule that
guessed would let a real missing figure through, and it fires as a judgement
so a person clears it in seconds.

**Rules get tightened, queues do not grow.** A judgement rule that produces
a large false-positive class gets rewritten until the class is acceptable.
Only the residue goes to a person.

The near-duplicate fingerprint is not the content hash. It is the lowercased
stem plus the sorted lowercased option texts, hashed to 16 hex characters.
It is the live rule, and it is worth knowing exactly what it does, measured
against the live tool:

| | Caught |
|---|---|
| A different case | yes |
| The options in a different order | yes |
| Padding around the text | yes |
| A rewritten stem | no |
| A reworded option | no |

So it is the fingerprint for the same question seen twice, not a similarity
measure. The same question harvested from two sources with the answers
shuffled is the duplicate that actually happens, and the exact hash would
never see it.

**The gate also owns the hash.** A gate that passes a row hands over a row
whose `content_hash` is correct, because the hash is the receipt every later
stage depends on.

**And the gate owns the duplicate check against what already exists.** A row
whose hash is already held is a duplicate, and a row whose id is already held
is the same row again. Both are counted, not silently overwritten.

### 4.3 Review

A person checks the content and records the check.

The production doctrine is that a human pass is the only thing that makes a
row servable, and the notes say plainly that if the serving app ever owns
human verification writes, that is a new capability with its own design. It
does not, so the review step belongs to the bank.

The review step has to produce a verification record the server's predicate
accepts, which means four things at once. The kind is `human`. The verdict
is `pass` or `fail`. The scope covers both `answer` and `explanation`,
because a pass that covers only the answer does not serve the row. And the
`content_hash` is the hash of the content as it stands at the moment of the
check, so the check cannot be applied to content that has since changed.

The bank's own AI checks write `ai_bulk` or `ai_single` records into the
bank's own store. They are evidence for the reviewer and they are never the
thing that makes a row servable. A bulk run and a single careful check are
different evidence, and the kind field is where that difference lives.

### 4.4 Ready

Ready is the output. It is a definition, not a writer. Placing the content is
not the bank's job, so what the bank owes is a bundle that is complete enough
that placing it is mechanical.

A ready bundle satisfies all of these.

| | The condition |
|---|---|
| **Gated** | Every rule in 4.2 ran, and the bundle carries the count of what was refused and why. |
| **Reviewed** | Every question in it carries a check over the answer and the explanation, at the hash of the content as it stands. Whose check it is does not matter here. |
| **Placed** | Every question has a subtopic that exists in the catalog, under the right exam and subject, and its topic belongs to that subject. |
| **Complete** | Every question has a stem, 2 to 5 options, an answer that names one of them, a difficulty in 1 to 5, and marks in the accepted range. |
| **Explanatory** | Every question carries an explanation with a key point and a body. A question with no explanation was never reviewable, and 50 of the 2,243 live rows are in exactly that state. |
| **Resolvable** | Every question that needs a stimulus carries the id of a passage that exists, and every figure carries a url that renders and a position that was set, not guessed. |
| **Identified** | Every question carries the hash of its content, computed the production way, and the hash matches the one the review covered. |
| **New** | No question in the bundle is a duplicate of anything already held, by hash or by near-duplicate. |

Two things follow from "ready" being a definition rather than a writer.

**The bundle is self-describing.** Whoever places it should not have to
consult the bank to know what a field means. The content carries the shape
from section 2, and the bundle carries the counts, the refusals and the
verification records that go with it.

**Ready is idempotent.** Placing the same bundle twice should not change
anything. So the content must not change between two placements, and the
hash must be stable, because a changed content changes the hash and a changed
hash voids the review that made the row servable.

---

## 5. The way back in

### 5.1 Reports

The API owns a `reports` table with a target-agnostic shape:

```sql
CREATE TABLE reports (
    id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
    reporter TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE(reporter, target_type, target_id, reason)
);
```

A report is a claim that something in the served content is wrong. Five
reasons, and a report can target any type, not only a question. The table
holds 1 row today.

The bank should consume reports and turn them into work. A report against a
row the bank produced means either the content is wrong, which the bank can
fix and re-gate, or the report is wrong, which the bank records and drops.
That judgement belongs to a person, and the bank's job is to present it
cleanly.

### 5.2 Drift

The server already detects drift. A row's stored `content_hash` is compared
to the hash its verification covered, and a mismatch drops the row out of
service until someone verifies it again.

The bank should run the same comparison against the content it has handed
over, so a row that changed comes back as work rather than as a silent loss
of coverage.

---

## 6. Volume

The bank is going to produce a lot of questions, so the rules have to hold up
when the content is big. These are measurements, not projections.

### 6.1 How much the API can carry today

The served side holds 2,243 questions and 2,268 verifications. The
aggregates that count them, on the keyless public routes, scan the whole
verification table with two `json_each` passes and a sorter. On the live
remote at 2,268 verifications that is 0.75 s.

On a local replica of the same data and the same queries, so the shape is
visible without the network:

| Population | the public aggregate |
|---|---|
| 2,243 questions, 2,268 verifications | 0.038 s |
| 22,430 questions, 22,680 verifications | 0.461 s |
| 112,150 questions, 113,400 verifications | 2.046 s |

Linear, and the remote engine is about 19 times slower than local sqlite on
the same data.

### 6.2 What that means for the bank

Three things change as the content grows, and all three are ours.

**Dedupe has to be cheap.** The exact hash makes a duplicate check a lookup.
The bank keeps a local index of the hashes it has handed over and of the
hashes production holds, refreshed on a schedule, so a duplicate check is a
lookup rather than a scan of the whole bank.

**Near-duplicates become the real problem.** Two exact hashes never collide,
so the exact hash only catches a row that was copied verbatim. The
near-duplicate fingerprint catches the reworded copy, and the live bank
already carries it. At volume, that rule is what stops the same question
appearing three ways.

**The gate has to be airtight, because nobody can read the output.** At 2,243
questions a person can skim a refusal list. At 100,000 they cannot, so the
gate's job shifts from catching what a reviewer would catch to catching what
a reviewer would not. That means the mechanical rules matter more, not less,
as the bank grows, and it means the gate's own coverage is worth measuring
and reporting on its own.

**Media stops being a corner case.** 71 figures today becomes 71,000 at the
same ratio, and every one of them is a url pointing at someone else's
server. The source url keeps working, so the asset pipeline is not urgent,
but the cost of finding out later is proportional to the size of the bank,
and the bank is cheapest to fix early.

---

## 7. What the bank never does

- **Never serves.** The API serves.
- **Never places content in the served tables.** That is a separate piece of
  work, and the bank's job is to make it mechanical.
- **Never presents an AI check as a human one.** A person signs it, and only
  a human pass makes a row servable.
- **Never guesses.** The figure position is data. A topic placement comes
  from the catalog.
- **Never drops a refusal.** Every rule that says no says why, and the count
  is reported.
- **Never hands over a row the gate has not passed.** Nobody downstream will
  check it, and one bad row breaks an endpoint for everyone.

---

## 8. What the bank produces

A ready bundle, made of:

| Produced | Shape |
|---|---|
| A question | The 17 columns in 2.2, with `content_hash` and `text_norm` computed by the bank. |
| A passage | The 9 columns in 2.4, when the question points at one. |
| A verification record | `kind`, `verdict`, `scope`, `verifier`, `detail`, `content_hash`, `created_at`. The bank writes `ai_bulk` and `ai_single` into its own store. A person writes `human`. |
| A media url | The bank's own url for a stored asset, in place of the source url, once the asset exists. |
| The counts | How many rows passed, how many were refused, and why, per rule. |

---

## 9. Where the code stands against this

### 9.1 Already right

- **The ports.** `Source`, `ImageDescriber`, `Explainer`, `Tagger`,
  `AnswerVerifier`, `CatalogReader`, `MediaStore`, `StagingStore`,
  `MediaFetcher`, `MediaValidator`.
- **The catalog is read, not copied.** The catalog reader queries the
  server's `subjects`, `topics` and `subtopics`.
- **The shape.** `RichText { text, inline }` and `Inline { start, len, kind }`,
  the production shape, with one vocabulary. The fingerprint matches
  production exactly, verified three ways on all 2,243 production rows:
  production's stored hash, `tools/review.py`, and the bank.
- **The gate.** Built, strict, machine only, and total. The default is fail.
  Every refusal goes to a person, and a clearance is recorded with a reason.
  Verified against the live bank: 2,178 of 2,243 live rows pass, and the
  counts per rule are pinned by a live contract test.
- **The passage as its own object.** A `passages` table in the bank, a
  `passage_id` on the question, and the kind as a closed list of production's
  four.
- **Dedupe.** Two fingerprints, a local index of both, and a refresh that
  reloads the index from production. The check is a lookup, so it holds up
  when the bank is big.
- **The media store** is content addressed, keyed by the sha256 of the bytes.
- **The state machine's spine**, from `planned` to `ready`, maps onto the
  jobs.

### 9.2 Wrong today

| What | Should be |
|---|---|
| The bank never refreshes the reports | the report log records what was acted on, and the reports are read on a schedule |
| The audit is not run against real content | the agreement rate is the number that decides how much content can move, and it has never been measured on a real run |
| The bundle is not placed anywhere | placing it is a separate piece of work, and the bank stops at ready |
| There is no `live` state and no `reported` state | content that has been handed over has to stay tracked, and a report has to become work |
| Nothing checks for drift | the server's own predicate detects it, and the bank should run the same check against what it handed over |
| The bank has no notion of a ready bundle | a definition of done, with the counts that go with it |
| The bank never refreshes the index | the index is a cache of what production holds, and it has to be brought up to date on a schedule |
| Nothing drives the loop | the steps exist and are wired to services, but there is no runner yet, so nothing calls them on a schedule |

### 9.3 There, but empty

Two models exist with no implementation behind them, and both are central.

**`GateVerdict`.** It carries `passed`, a list of `Issue` with a severity, and
a rules version. That is the right shape for the gate's answer. No code
produces it, so nothing can fail yet.

**The `verifications` list on `Evidence`.** It carries a kind, a verdict, a
scope, a content hash, a reviewer, a note and a producer. The server's record
has `auto_rule`, `ai_bulk`, `ai_single` and `human`, and the bank's `ai`
collapses the two AI kinds into one. A bulk run and a single careful check
are different evidence.

### 9.4 The order that makes sense

1. **The gate.** Built. Strict, machine only, 100% of rows, with the refusal
   counts. Verified against the live bank: 2,178 of 2,243 live rows pass, and
   the counts per rule are pinned by a live contract test.
2. **The passage as its own object.** Built. A `passages` table in the
   bank, a `passage_id` on the question, and the kind as a closed list of
   production's four.
3. **The key rename to `inline`.** Built. One vocabulary, the production
   one, and a staged payload is the shape the live tooling reads.
4. **Dedupe.** Built. The exact hash and the near-duplicate fingerprint, a
   local index of both, and a refresh that reloads the index from
   production. Verified live: a production row fed back in is refused as
   `duplicate_exact`.
5. **The review step.** Built. The machine checks every row and the check
   is recorded with its kind, its scope, the model and the reason. The
   audit samples the machine's work and measures the agreement.
6. **The ready bundle.** Built. Eight conditions, each machine-checkable,
   and a report that says where every row stands.
7. **The report consumer and the drift check.** Built. A report against a
   row the bank placed reopens it, and a report against a row it did not
   place opens a new item. Drift is the hash comparison against what
   production holds, and a drifted row goes back to the bench.

The media work waits. The source url on the mark renders today, and the asset
pipeline is a later cleanup rather than a blocker for any of the seven above.

---

## 10. Sources

| What | Where |
|---|---|
| The current production types | `src/core/models/domain.rs` |
| The wire shapes | `src/core/models/wire.rs` |
| The live DDL | the production database, read on 2026-10-21 |
| The serving predicate and the row readers | `src/store/catalog.rs` |
| The pipeline doctrine | `docs/NOTES.temp.md` |
| The live gate rules and the fingerprint | `tools/review.py` |
| The archived tree, a source of capabilities and never of structure | `utmelab-api-old/` |
| The decision log, the rich text rule and the figure rules | `utmelab-api-old/docs/` |
