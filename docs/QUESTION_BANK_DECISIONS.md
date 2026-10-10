# Question Bank — Decision Log & Intent

> **Workspace:** this is `utmelab-api`'s decision log. It lives here, not in the UTME-Lab
> repo — the bank is a separate product with its own repo; the app is one consumer.
> **Status:** living decision record. Written **before** any change to data or code.
> **Rule of this file:** every decision gets an ID, a status, and a reason. Nothing
> is changed in `data/` until it is recorded here.
> **Related (still in the UTME-Lab repo):** `docs/QUESTION_BANK_AUDIT.md` (vendor research
> + proposed schema) and `docs/GAPS.md` (gap list). This file is the **decision layer**
> over both. Sections below that cite `data/bank/…` refer to the **UTME-Lab** working
> copy; `data/api/…` refers to **this** repo.

---

## 1. Intent (load-bearing — changed 2026-10-10)

The question bank is **not** an internal feature of UTME Lab. It is a **product**.

1. UTME Lab is the **anchor consumer** — it must build fast against the bank.
2. The bank is **also a public, paid API** that third parties can call.
3. Decisions are made so the app can be built **quickly** against a small set of
   **defined constants** (the schema), while leaving the **door open** for other
   exams, other clients, and later extensions.
4. Priorities, in the user's stated order: **efficiency → simplicity of use →
   security last.** Security is not ignored; it is deliberately *deferred* so it
   does not distort the schema before usage is understood.

### 1.1 What this changes about past decisions

- The audit's *"no vendor calls at runtime, own bank is the moat"* (§9) was written
  for an internal-only product. It still holds — but the **moat is now also the API**.
- Anything internal-only (RAM bundle, `cfg(feature)` gates, hardcoded registries)
  must be re-examined: it may be fine for the app but **wrong** for a public API.

---

## 2. Measured facts (this repo, 2026-10-10)

Measured directly from `data/bank/questions.json` (3,442 rows) and the source tree.
These **correct** parts of `QUESTION_BANK_AUDIT.md` and `GAPS.md` — see §6.

### 2.1 Shape of the bank
- 3,442 rows, **year = 2025 only**, no other year present.
- **34 distinct subjects** in the bank.
- ~**1,061 bytes/question** raw, ~**127 bytes** gzipped.
- English Language 249 rows; Music 82; Arabic 80; Book Keeping 31; **all others exactly 100**.

### 2.2 The three subject catalogs do not line up
| Catalog | Count | Source |
|---|---|---|
| Bank | 34 | `data/bank/questions.json` |
| Syllabus | 34 | `crates/server/src/syllabus/` (39 files incl. `mod.rs`) |
| `SUBJECTS` registry | **16** | `crates/core/src/models/subject.rs:42` |

- **1,549 questions reachable** through the registry; **1,893 unreachable (55%).**
- **17 subjects exist in bank + syllabus but have no registry entry**: Fine Arts,
  French, Further Mathematics, Hausa, Igbo, Yoruba, Arabic, Music, Marketing,
  Insurance, Home Economics, Office Practice, Physical Education, Animal Husbandry,
  Book Keeping, Catering Craft Practice, Computer Studies, Data Processing.
- **`History` and `Civic Education` are flagged `has_bank: false`
  (`subject.rs:57-58`) but each has 100 questions in the bank.** A flag bug, not a
  data gap.
- Most of the 17 are **not JAMB UTME subjects** (Animal Husbandry, Catering,
  Office Practice, Home Economics, Insurance are WAEC/NECO). So the registry
  cannot simply be widened to 34 without lying to JAMB candidates.

### 2.3 Topics are in better shape than documented
- **317/317 bank topic tags exactly match an authored syllabus topic name. Zero drift.**
- **328 of 329 bank topics have ≥ `MIN_TOPIC_QUESTIONS` (4) questions.** The
  `MIN_TOPIC_QUESTIONS` "coming soon wall" does **not** exist in the bank.
- But: **542 syllabus topics are authored, only 317 have questions → 225 (41%) are
  empty.** e.g. Physics 45 syllabus topics / 10 bank topics; History 43/12;
  Government 32/10. The real wall is syllabus breadth vs bank depth.

### 2.4 Per-row field coverage (3,442 rows)
| field | present | note |
|---|---|---|
| `id, subject, year, content, options, answer, explanation` | 3,442 | |
| `topic` | 3,386 | **56 missing** — Music 28, **Mathematics 19**, Office Practice 7, Yoruba 2 |
| `image` | 3,193 key / **170 non-null** | |
| `content_hash` | 3,193 | **249 missing — exactly the 249 English rows** |
| `explanation` non-empty | 3,220 | **222 empty (6.4%)** |
| `exam, section, passage, subtopic, difficulty, marks, estimated_time, verified, source` | **0** | none exist |

- The 249 English rows also lack the `image` key → they came through a **different
  ingest path** than the other 3,193. Provenance seam.

### 2.5 Serving today
- Serving is a **RAM read** of the JSON via `crates/server/src/db/bank.rs`
  (`OnceLock` at `bank.rs:29`); zero query, zero Turso.
- `crates/server/src/db/migrate.rs` contains **no `questions` table**. The only
  `CREATE TABLE questions` in the repo is a **test fixture**
  (`crates/server/src/db/questions.rs:441`). The live Turso questions table is an
  **orphan** — no migration owns it.

### 2.6 Scale headroom
| rows | raw | gzipped |
|---|---|---|
| 3,442 | 3.6 MB | 439 KB |
| 64,000 | 68 MB | ~8 MB |
| 200,000 | 212 MB | ~25 MB |

64k in one table is not a capacity problem for SQLite/LibSQL. Serving is per-paper
(4 subjects ≈ 180 questions), so the device never downloads the whole bank.

---

## 3. Decisions

Status: **PINNED** = agreed, do not relitigate without a reason. **OPEN** = needs study.

| ID | Decision | Status | Reason |
|---|---|---|---|
| **D1** | Subject catalog lives in a **DB table with an `exam` column**, not the hardcoded `SUBJECTS` static. The Rust static becomes a cache of the catalog, not the source of truth. | **PINNED** (user, 2026-10-10) | 16-vs-34 mismatch; `has_bank` lies; JAMB-vs-WAEC must be *data*, not omission. Also the shape a public API needs. |
| **D2** | `exam` is on the **critical path** — added to the question schema and the subject catalog before anything else. | **PINNED** (implied by D1) | Every one of 3,442 rows is implicitly JAMB; without `exam` the catalog cannot be built. |
| **D3** | **Simple paging** — plain `page` / `total_pages` / `total_records`. | **PINNED** (user, 2026-10-10) | Simplest thing that serves both the app and a public API. No cursors. |
| **D4** | All question **rows in one table**; all **catalogs** (subjects/topics) in one table keyed with `exam`. No sharding, no per-subject tables. | **PINNED** | 64k rows is a non-issue for SQLite/LibSQL; simplicity wins; room to grow. |
| **D5** | The **JSON is a placeholder**, not the plan. Decisions must hold for both the JSON and the DB. | **PINNED** (user, 2026-10-10) | Explicit: "the json is just a placeholder". |
| **D6** | **Security is last** — deliberately deferred, not ignored. | **PINNED** (user, 2026-10-10) | Stated priority. Do not let auth/rate-limit design distort the schema before usage is understood. |
| **D7** | Decisions are written here **before** any change to data or code. | **PINNED** (user, 2026-10-10) | Stated rule. |
| **D8** | Add **`exam`** to every row of `data/bank/questions.json` now: `"JAMB"` for the 25 JAMB-owned subjects, **`""` (empty)** for the 9 non-JAMB subjects. | **PINNED** (user, 2026-10-10) | Unblocks D1/D2. Confirmed by user that IBASS lists 25 subjects. Non-JAMB rows are deliberately left empty, not guessed — WAEC/NECO assignment is still open (O1b). |
| **D9** | Apply the **same `exam` tagging to the live Turso `questions` table** — `ALTER TABLE … ADD COLUMN exam TEXT`, then set per subject. Same 25/9 split. | **PINNED** (user, 2026-10-10) | "let do same there before we look into others" — keep JSON and DB consistent so the catalog has one truth. |
| **D10** | **Do NOT rename subjects in Turso** — it is already canonical. The **JSON** is the store carrying long-form names and is the one to normalize later. **Deferred, not applied.** | **DEFERRED** (user, 2026-10-10) | Renaming Turso would break the one store that already matches the registry. JSON normalization is the correct direction but deliberately postponed. |
| **D11** | The **canonical schema constant** (below). Adds `passage_id` and **answer-by-option-id**. Drops `sitting` and `format`. Keeps `marks`. | **PINNED** (user, 2026-10-10) | `passage_id`: the data already assumes passages (598 Turso rows say *"In question numbered N above"*) and none are stored. Answer-by-id: shuffling must never invalidate an answer. |
| **D12** | **The constant is constant.** Every other artifact adapts to it — not the reverse. | **PINNED** (user, 2026-10-10) | Stated law. |
| **D13** | **The JSON is the fast-adapting store; Turso is the slow one.** That is *why* the JSON exists — it serves the app now while Turso is worked to the same constant. | **PINNED** (user, 2026-10-10) | "the json is easy to quickly adapt, the turso will need time". The JSON is not a throwaway; it is the bridge. |
| **D14** | **Five tables**: `questions`, `passages`, `subjects`, `topics`, `subtopics`. Subtopics are one level deep, no `parent_id`. | **PINNED** (user, 2026-10-10) | §3.1.2 argues each table by what breaks without it. Subtopics are justified by JAMB's own two-deep catalog (Biology 24/62/173) and by drill granularity. |
| **D15** | **Options shape.** `Option { id, text }` with single-letter ids (`a`–`e`). **`label` is not stored** — it is assigned from array position at render time. `answer` references the id. | **PINNED** (user, 2026-10-10, "your call") | A label is a display position, not an identity. Index-based `answer` was rejected on failure-mode grounds: a forgotten remap silently marks correct answers wrong. 26 letters is ample for Nigerian MCQ (observed max 5 options); letters keep the wire readable. |
| **D16** | **Where topics come from.** Topic names = **JAMB's official areas of concentration, verbatim**. Subtopics are **derived, not transcribed** — a topic gets them only once it has enough questions to drill. **No sync mechanism, no active flags.** | **PINNED** (user, 2026-10-10, "your call") | Verbatim names mean the consumer sees exactly what JAMB told them to revise. Deriving subtopics skips the fiddliest part (JAMB nests four levels deep: part → topic → a/b/c → i/ii) for structure that is not examinable. **Absence is the signal** — a topic with no questions does not appear, which deletes the maintenance problem rather than solving it. |
| **D17** | **The explanation is three fields** — `key_point` (required), `body` (Markdown subset, formulas inline), `trap` (optional). **`verified: bool`** joins the question as a static credential. **No formula field**; **no per-option notes**; **no runtime signals in the bank.** | **PINNED** (user, 2026-10-10) | §3.1.7–3.1.10. Three consumers need three slices of one explanation, so it is structured, not a blob. `trap` is the differentiator no vendor offers. `verified` is the static half of trust — votes/disputes are runtime data and belong to the app, not the bank. |
| **D18** | **Study notes: shape recorded, explicitly NOT v1.** One note per subtopic — `overview`, `must_know[]`, `formulas[]`, `traps[]`, `worked?`. **Not merged into explanations.** Link is the existing `subtopic_id`; no new field. Activating it means a **sixth table (`notes`)**. | **DEFERRED — not v1** (user, 2026-10-10, "not v1, but worth noting now as constant") | Recorded now so it is settled before it is needed, and so nothing else has to be revisited when it is. §3.1.11. |
| **D19** | **The syllabus surface.** Six endpoints; every node returns **coverage** (`question_count`, `note_available`) beside name/order/weight. **`objectives: Vec<String>` on subtopics**, returned **by default — no flag**. Catalog never paginates; questions use D3 simple paging. Catalog is addressed by **slug**, questions by **id**. | **PINNED** (user, 2026-10-10, "useful & simple as possible") | §3.1.12. A syllabus that returns only names is a dump; coverage is what makes it actionable. `objectives` is examinable content every competitor publishes (JambKit: 173 for Biology) and pairs with coverage as *"what you must do"* + *"what you can practise"*. **One response shape, no flag** — two shapes is two things to get wrong. |

## 3.1 THE CONSTANT (D11)

### 3.1.1 The question shape

```rust
Option { id: String, text: String }        // id is "a".."e"; text may carry inline LaTeX

Explanation { key_point: String, body: String, trap: Option<String> }

Question {
  id, exam, subject, year,
  text, options: Vec<Option>, answer,      // answer = an Option.id, never a label or index
  subtopic_id, section, passage_id, image,
  explanation: Option<Explanation>,
  marks, difficulty, verified,             // verified = static credential, ships with content
}
```

**Field decisions and their grounds:**
- `text` (not `content`/`prompt`) — matches ALOC/EDV/Sdash naming; `Question.text` avoids stutter.
- `options` is **2–5, never fixed at 4** — 12,915 existing rows carry an `E`.
- `answer` = **option id**, not label or index. Contract: options carry stable ids,
  shuffling is a pure permutation that never touches an id, so `answer` never needs
  remapping. JAMB draws 40 of thousands and randomises every one.
- **`label` is not stored.** A label is a *display position*, not an identity — it is
  assigned at render time from the array index. Storing it is exactly what makes
  `answer: "C"` fragile: the moment you shuffle, the letter points at a different
  option. Rejected `answer: u8` (index) too, on failure-mode grounds: every shuffling
  code path would have to remember to remap, and forgetting once **silently marks
  correct answers wrong**. With ids, shuffling is only ever a permutation.
- Wire format emits `options: [{id, text}]` with labels assigned from position at
  serve time, so a consumer rendering in stored order still sees A–D and the format
  stays familiar. It also makes `answer` readable at a glance: `answer: "b"` is
  verifiable against `options[1]` without counting.
- `section` — the **marks key**. English is not flat: comprehension 3, cloze 2,
  oral-forms 1, while other subjects are a uniform 2.5. `marks` is therefore **not
  derivable from a question count** and must be stored.
- `passage_id` — normalized in storage, **resolved inline on read**, so a consumer
  makes one call and never joins.
- `explanation` — see **§3.1.7**. Three discrete fields (`key_point` / `body` /
  `trap`) rather than one blob, because three different consumers need three
  different slices and a blob forces them to parse.
- `difficulty` 1..=5, derived from solve-rates, never hand-set.
- `verified` — **static** credential only. Upvotes, disputes, discussion counts
  and report totals are **runtime data and live in the app's database, not the
  bank.** Content carries its credentials; the crowd lives in the app.

**Deliberately excluded:** `sitting` (JAMB sits yearly) · `format` (duplicates
`options.is_empty()`, and a derivable field can be wrong) · `estimated_time`,
`source` (reserved — add when earned) · **`Option.image`** (diagrams in option
sets are real — ALOC carries image URLs — but we cannot point to a case today;
add when a question forces it, one migration) · **`Option.note`** (per-option
"why this is wrong" — parked, see §3.1.7) · **`is_correct` on an option**
(would leak the answer inside the options array).

**LaTeX convention is shared** by `Option.text`, `Question.text` and `explanation`:
one rule to learn, not three.

### 3.1.2 FIVE TABLES (D14)

| # | Table | Rows | Holds |
|---|---|---|---|
| 1 | `questions` | 68,613 → grows | The bank |
| 2 | `passages` | 0 today | Shared stimulus (English comprehension/cloze) |
| 3 | `subjects` | 34 | The subject taxonomy, per exam |
| 4 | `topics` | 542 | Syllabus topics within a subject+exam |
| 5 | `subtopics` | ~1,100 | Drill-granular practice units |

```sql
subjects   (slug PK, exam, name, is_compulsory, full_exam_questions)
topics     (slug PK, subject, exam, name, order, weight)
subtopics  (slug PK, topic FK, name, order, objectives TEXT[])
passages   (id PK, exam, subject, year, kind, title, author, text)
questions  (id PK, exam, subject, year, text, options, answer,
            subtopic_id FK, section, passage_id FK, image,
            explanation, marks, difficulty)
```

**Why each table exists — what breaks without it:**

**1. `questions`** — the product. Everything else is a way of slicing it.

**2. `passages`** — JAMB English sets 5 questions off one comprehension passage and
10 off one cloze. 598 existing rows read *"In question numbered N above"* and point at
a passage stored nowhere; no passage over 417 characters exists in either store.
Inlining instead would multiply payload and make "fetch this comprehension set"
impossible. Normalised in storage, resolved inline on read.

**3. `subjects`** — the replacement for the hardcoded `SUBJECTS` array that caused the
16-vs-34 mismatch. It is the thing that *filters*: `SELECT DISTINCT subject` would
return whatever was ingested, including Animal Husbandry, which no JAMB candidate may
pick. Carries the metadata that does not belong on a question (`full_exam_questions`
60/40, `is_compulsory`). Its `name` is **JAMB's official name**, verbatim — single
source of truth, no second name (D20).

**4. `topics`** — the syllabus taxonomy. Not derivable from questions: questions know
their topic as a string but carry none of `order`, `weight`. Also holds topics with
zero questions, which any `DISTINCT` query would miss — real value for a paid API
buyer who wants the full taxonomy.
`exam` sits here because a topic belongs to *an exam's syllabus*: WAEC Mathematics
and JAMB Mathematics share topics and diverge.

**5. `subtopics`** — one level, no `parent_id`. Justified three ways:
- **JAMB's own catalog is two-deep**: 24 topics / **62 subtopics** / 173 objectives
  in Biology; 33 / **41** / 76 in Government. A flat taxonomy strands those.
- **WAEC and NECO are exactly two deep** (`11 Equilibrium of forces` → `11.1`, `11.2`,
  `11.3`). Nothing at this level goes three deep.
- **Objectives are not a level.** JAMB nests objective inside subtopic, but an
  objective ("identify the units of length, area, volume…") is a teaching statement,
  not practice-granular. Nobody filters questions on it.

**The student argument that settles it.** A weak signal of *"bad at Motion, 9/28"*
forces the student to redo all 28 to fix maybe 4. With subtopics the signal is
*"bad at Projectile motion 2/9 and Newton's laws 2/12"* — a **21-question sitting**,
not a paper. Subtopics are what make (a) honest mastery at a pool small enough to be
true, (b) a *named* failure rather than a vague one, (c) skipping what you already
mastered, and (d) a mistake bank that can say "you keep missing Principle of moments."
They appear in the UI only on drill / weak-report / mistake screens — topics stay the
browsing layer — so they cost one table and almost no interface.

### 3.1.5 Where the taxonomy comes from (D16)

**Topics: JAMB's official "areas of concentration", verbatim.** Published per subject at
`efacility.jamb.gov.ng` / `jamb.gov.ng/ibass`, republished **yearly** ("subject to
modification at any year"). We do not coin names — a student reading our topic list
must see exactly what JAMB told them to revise, or we look less authoritative than a
competitor that merely copied the syllabus.

**Subtopics: derived, never transcribed.** JAMB's own outline runs four levels deep
(`SECTION A` → `1. Living organisms` → `a. Characteristics` → `i. Cell e.g. Euglena`).
Only the top two are examinable; "SECTION A" is a grouping, not a testable thing.
Rather than flatten that structure, **a topic acquires subtopics only once it holds
enough questions to drill.** The schema permits zero subtopics per topic, so this is
incremental and blocks nothing.

**No sync mechanism.** No revision flag, no active/inactive column, no catalog-version
table. **Absence is the signal**: a topic with no questions behind it simply does not
appear. If JAMB drops a topic we stop tagging new questions and it fades out; if JAMB
adds one, the row appears when we first have content for it. This *deletes* the
maintenance burden instead of solving it — the deliberate trade of a faithful mirror
for a catalog that is useful and cheap to run.

**Competitive context (recorded so we aim correctly).** The taxonomy is **table
stakes, not differentiation.** JambKit already publishes JAMB's areas of concentration
mapped to question counts (Biology "24 topics / 62 subtopics / 173 objectives";
Government "33 / 41 / 76"). Our differentiation sits *upstream* of the taxonomy:
the questions, the explanations, and subtopic-level weak-spot diagnosis. Knowing
"you are weak at Principle of moments" is the product; the taxonomy only lets us say it.

**Build order.** English first (compulsory, 60 of 180 questions, and passages are
blocking it anyway), then Mathematics / Physics / Chemistry / Biology, then **Computer
Studies and Physical & Health Education** — newly added JAMB subjects with no
competitor coverage (the audit records ALOC as lacking Computer entirely), which is
where the catalog is an advantage rather than a checkbox.

**Attribution.** Topic *titles* are reproduced; JAMB is credited as the source of the
taxonomy in the API. JAMB's *objective* text is not reproduced wholesale — it is
teaching copy, not catalog, and it is where the IP risk actually sits.

### 3.1.7 The explanation (D17)

```rust
Explanation {
  key_point: String,     // REQUIRED — one line, the thing to remember
  body: String,          // Markdown (documented subset), $$…$$ for formulas at point of use
  trap: Option<String>,  // why the tempting wrong answer is wrong
}
```

**Why three fields and not one string.** Three consumers need three different slices
of the same explanation: a flashcard app wants a teaser, a quiz app wants the working
shown on answer, a study-notes product wants all of it. A single blob forces every
consumer to *parse* prose to extract a slice, and parsing is where integrations break.

**`key_point`** is the reason the structure exists. A flashcard needs a teaser;
deriving "the first line of body" is fragile and produces mush. Making it required
forces authors to write a good one-liner — that discipline is worth more than the
field costs.

**`trap` is the commercial argument.** "You chose C because you confused *declared*
with *paid* dividend" is the highest-value sentence the product can produce, and **no
vendor offers it** — the audit found ALOC charges 10 credits per question just for the
basic explanation, and Sdash's solutions are frequently null. Structuring it separately
also makes it aggregatable: *"you keep missing Principle of moments"* requires it to be
queryable, not buried in prose.

**Body is Markdown, as a documented subset** — `##` headings, lists, `**bold**` /
`*italic*`, `` `code` ``, links, `$$…$$` LaTeX. **No raw HTML.** Every consumer already
ships a renderer so it costs them nothing; constraining the subset keeps output
predictable and lets us reject raw HTML outright. A typed block enum was rejected —
buyers would have to write a renderer before displaying anything, which is the wrong
first impression for a paid API, and it is rigid the moment a subject needs a structure
we did not predict.

**Market validation (research, 2026-10-10).** PassJAMB — a **paid** product at
₦1,500/month — states: *"Our explanations show the reasoning, the formula, and the
trap"*, and *"tap any wrong answer to see exactly why it's wrong."* This structure is
not speculative; it is roughly what the market already pays for.

### 3.1.8 Formulas

**Inline in `body`, never their own field.** A formula belongs in the explanation
*only when applying it is the thing being tested* — V=IR for a circuit question,
nothing for a Biology definition, nothing for English. That is a judgement made at the
point of writing, so it belongs inline where it is used. A separate `formula` field
would duplicate a line of `body` and sit empty on most questions — the sparse-field
problem D15 already settled.

**The JAMB formula sheet is a different artifact.** JAMB publishes an official
per-subject formula sheet (JambKit ships it as "the JAMB formula sheet"). That is
subject-level reference content, versioned by year, and genuinely sellable on its own.
It is **not** part of the question constant — and it collides with the **undecided
study-notes** decision. Flagged, not scheduled.

### 3.1.9 "Useful" — what earns a mark, and what does not

Looking for a helpful/upvote flag turned up something better. Myschool.ng's discussion
threads on a single Physics question contain:

> *"THE ANSWER SHOULD BE 11/9 NOT THE OTHER WAY ROUND"* (0 votes) ·
> *"I don't understand any of this"* · *"the diagram is not showing"*

Students do not upvote explanations. **They dispute answers.** That is a correctness
signal, and the first question a paying API buyer asks is *"how do I know these answers
are right?"*

But that tells us where the mark should **not** live. Votes, disputes, discussion counts
and report totals are **runtime data** — they change daily, and a per-question counter
is meaningless on its own and only useful in aggregate. Putting them on a content row
would mean rewriting 68k rows constantly to store a number nobody reads per-question.

**`verified: bool` is the static form of the same trust:** a human has checked the
question, its answer and its explanation. It ships with the content, never mutates, and
is directly filterable by a buyer (`?verified=true` — "give me questions my students can
trust"). It starts `false` everywhere until a human passes it, which is the honest
starting state *and* a real backlog metric.

**Rule that follows: content carries its credentials; the crowd lives in the app.**

### 3.1.10 Per-option notes — parked

PassJAMB's *"tap any wrong answer to see why it's wrong"* is the natural generalisation
of `trap`: `trap` is the single most-picked distractor, a per-option note covers all of
them. It is **not** in the constant, on cost grounds: 68k questions × 4 options ≈
**275,000 "why wrong" strings** — the largest single authoring burden in the project —
while `trap` already covers the common case. Add it when a subject genuinely needs it,
by the same rule that parked `Option.image`.

### 3.1.11 Study notes — shape recorded, NOT v1 (D18)

```rust
Note {
  subtopic_id,             // one note per subtopic
  overview: String,        // Markdown — the concept, taught plainly
  must_know: Vec<String>,  // 3–7 bullets: the facts the exam actually tests
  formulas: Vec<String>,   // LaTeX — empty for Biology, English, Civic
  traps: Vec<String>,      // how students actually lose marks here
  worked: Option<String>,  // one full worked example, Markdown
}
```

**Why it is not merged into explanations.** They share vocabulary but not content: an
explanation is the *instance* ("10% of 2,000,000 = 200,000; option B; GH¢ 20,000
confuses face value with paid-up capital"), a note is the *general case* (dividends are
declared by directors, approved by members, paid on paid-up capital, never face value).

The deciding factor is **scale**: 68,613 questions across ~542 topics/subtopics is
**~130 questions per subtopic**. Writing the concept 130 times is not sustainable; it
is written once in the note. *At 500 total questions the merge would be correct — this
design changes at scale, and we are past it.*

**The link costs nothing.** Every question already carries `subtopic_id`, so "which note
explains this question" is already answered by the schema — no `note_ref`, no join table,
no sync. This matches the paid market: PassJAMB's *"tap any wrong answer to see exactly
why it's wrong **and which concept to revisit**"* is two linked layers, not one.

**The duplication that does exist is formulas, and it is acceptable.** A consumer
fetching a single question must get a usable answer in **one call** — an explanation
saying "see Note: Principle of Moments" forces a second request and strands anyone who
asked only for the question. Self-containment at the API boundary is worth more than
DRY. The formula still has **one canonical home** — the note, and the JAMB formula sheet
(§3.1.8) — so there is no second source of truth.

**Activation condition.** A note exists **only for subtopics with enough questions to
practise against.** Three questions on a subtopic means the note and three explanations
are the same content and the note is padding. Same rule as subtopics themselves (D16).

**Authoring reality.** Largest content job in the project — a page per note, not a
paragraph — so it is scoped to the build order (English, then Maths/Physics/Chem/Bio).
Competitors already ship AI prose (PassJAMB "AI explanations written in simple English",
Myschool's AI explanation), so AI-assisted + human-reviewed is the only viable
production model. **The differentiator is not the AI — it is that notes are checked
against the questions we actually have.**

**Why this is the moat.** The audit's finding is that questions are *commodity* — ALOC,
EDUV, Sdash and MyQuest all sell past papers, and that content already circulates in PDFs
across Nigerian campuses. Nobody has a note per subtopic written at a level a student
actually reads, pointing at the exact questions that test it.

### 3.1.12 The syllabus surface (D19)

**Principle.** A syllabus endpoint that returns topic names is a **dump** — it helps no
one. The question someone actually has is *"what do I need to learn, and can I practise
it?"* So every node answers three things: **what it is** (name), **where it sits**
(order, weight), and **can I act on it** (`question_count`, `note_available`).

```
GET /v1/exams                    → the exams we carry
GET /v1/exams/{exam}/subjects    → subjects offered in that exam
GET /v1/subjects/{slug}          → one subject, its exams, its totals
GET /v1/subjects/{slug}/syllabus → the whole tree, with coverage   ← carries the weight
GET /v1/topics/{slug}            → one topic + subtopics + counts
GET /v1/subjects/{slug}/coverage → counts only, no tree
```

```json
{
  "exam": "JAMB",
  "subject": { "slug": "mathematics", "name": "Mathematics" },
  "topics": [
    { "slug": "indices-logarithms-surds", "name": "Indices, Logarithms and Surds",
      "order": 4, "weight": 8, "question_count": 212, "note_available": true,
      "subtopics": [
        { "slug": "laws-of-indices", "name": "Laws of Indices", "question_count": 74,
          "objectives": ["Apply the laws of indices to simplify algebraic expressions"] }
      ] }
  ],
  "summary": { "topics": 23, "topics_with_questions": 23,
               "subtopics": 62, "subtopics_with_questions": 58, "questions": 4370 }
}
```

**Rules.**
- **Catalog does not paginate; questions do.** A subject syllabus is ~23 topics / ~62
  subtopics — it fits. A question list is unbounded, so that is where **D3's simple
  paging** applies.
- **Slugs for catalog, ids for questions.** Topics and subjects are readable, cacheable and
  survive the yearly JAMB revision (D16 keeps topics stable). Nobody types question ids.
- **`exam` is required where it changes the answer** — WAEC Mathematics ≠ JAMB Mathematics.
- **`objectives` live on subtopics, default-on, no flag.** One attachment path, matching
  notes (D18). A topic with no subtopics shows none — which correctly signals *"nothing
  here yet"*, consistent with D16's absence-is-the-signal rule. **One response shape**: a
  flag means two shapes to build, document and keep correct.
- **`keywords` is dropped.** It existed to make a text classifier match topics; the
  `subtopic_id` FK deleted the classifier. Search matches on name.

**Why `objectives` earns its column.** JAMB syllabi are built from aims → topics →
*contents* → *objectives*, and the objectives ("candidates should be able to…") are the
examinable statements. JAMB's `contents` bullets are structurally what our subtopics
already are, so that is covered — objectives were the uncovered half. Every competitor
publishes them (JambKit counts **173** for Biology; jambsyllabus.com covers all 25), so
a consumer expects them. Paired with coverage they give the promise of a syllabus in two
fields: **what you must be able to do** + **what you can practise**.

**Deliberately not modelled.** *Scheme of examination* — for JAMB it is three constants
(English 60/100, others 40 @ 2.5, 120 min), so it is a constant, not content; WAEC makes
it real later. *Recommended texts* — annual and JAMB-published, already half-captured by
`passage.title/author`. *Included/excluded notes* — WAEC-specific.

**⚠ Known future problem, recorded not solved.** WAEC Mathematics Paper 2 is
**"answer 10 of 13"** — students attempt a subset. Our `marks` assumes every question in a
paper counts toward 100, which is correct for JAMB and **wrong for WAEC**. Paper assembly
will eventually need *"which questions does a candidate actually attempt"*. Flagged so it
is not rediscovered when a WAEC mock scores wrong.

### 3.1.13 O1b — the 25 subjects confirmed (D20 falls out of it)

`efacility.jamb.gov.ng` and `www.jamb.gov.ng` both time out and IBASS is a JS app, so
the official page could not be loaded directly. Confirmed via the search index's crawl of
**`ibass.jamb.gov.ng/e-syllabus`** plus three independent listings.

**The decisive detail — official pagination.** IBASS shows **"12 entries" per page across
3 pages**, and page 1 is verbatim:

> Agriculture science · Arabic · **Art** · Biology · Chemistry · Christian religious
> studies · Commerce · **Computer studies** · Economics · French · Geography ·
> Government

Exactly 12, in alphabetical order. Page 2 takes the next 12 (Hausa → Use of English),
leaving **Yoruba alone on page 3**. **12 + 12 + 1 = 25.**

Corroborated by: the user's own count on the official site; `jambgovng.org`'s numbered
list (items 1–25, ending Physical and Health Education); and academics.ng's older
23-subject list, which is exactly 25 minus the two additions.

**Two independent confirmations that the new subjects are real:** *Computer Studies*
appears in IBASS's own subject list, and *Physical and Health Education* is item 25 on
the numbered list.

**The consequence — D20.** JAMB's official names differ from ours: **Art** (we say Fine
Arts), **Use of English** (we say English), **Principles of Accounts** (we say
Accounting). The tempting fix was a `display_name` column carrying both. Rejected —
two names is two sources of truth, which is the same mistake that produced the 16-vs-34
registry mismatch, the alias table, and the free-text topic tags.

**Subjects are renamed to JAMB's official naming, verbatim, and `display_name` is
removed.** `subjects { slug, name, is_compulsory, full_exam_questions, exams[] }`. This
extends D16's "verbatim from JAMB" rule from topics up to subjects, where it belongs —
and it retires `SUBJECT_ALIASES` entirely, since nothing needs a second name to resolve
against any more.

**One caution when transcribing:** take exact spellings from each subject's official PDF,
not from IBASS's web UI strings — the UI renders "Agriculture science" (lowercase `s`)
and abbreviates Art, which are display artefacts, not the official names. **D16's
"absence is the signal" rule applies here too: if a name cannot be read off the official
document, it is not confirmed.**

### 3.1.14 Subjects are exam-scoped (D21) + the duplication principle (D22)

**The problem that forced it.** The boards do not agree on names, and not cosmetically:

| Concept | **JAMB** | **WAEC** | **NECO** |
|---|---|---|---|
| English | **Use of English** | **English Language** | **English Language** |
| Mathematics | Mathematics | **General Mathematics** | Mathematics |
| Accounting | **Principles of Accounts** | **Financial Accounting** | **Accounting** |
| Art | **Art** | **Visual Arts** | **Visual Arts** |
| Physical & Health | **Physical and Health Education** | **Health Education** | **Physical Education** |
| Home Economics | **Home Economics** | **Home Management** | **Home Management** |
| Civic Education | *not offered* | **Civic Education** | **Civic Education** |

D20 ("use JAMB's name") fails on two counts: JAMB has **no name** for the 9 subjects it
does not offer, and for subjects in *both* boards there are two equally official names.
One name per concept cannot express that.

**The fix — one row per exam, not one row tagged with exams.**

```sql
subjects (slug PK, exam, name, is_compulsory, full_exam_questions)

{ "slug": "use-of-english",       "exam": "JAMB", "name": "Use of English",      "is_compulsory": true,  "full_exam_questions": 60 }
{ "slug": "english-language",     "exam": "WAEC", "name": "English Language",    "is_compulsory": true,  "full_exam_questions": 80 }
{ "slug": "general-mathematics",  "exam": "WAEC", "name": "General Mathematics", "is_compulsory": true,  "full_exam_questions": 75 }
{ "slug": "mathematics",          "exam": "JAMB", "name": "Mathematics",         "is_compulsory": false, "full_exam_questions": 40 }
```

`slug` is the **exam's own** name, so it is verbatim from that board by construction.

**Why this is not a compromise.** The alternative — one row plus a per-exam alias list —
buys fewer rows at the cost of every consumer having to resolve names before they can
display them, and every writer having to keep two lists in sync. Duplicating the row
means a consumer reads `subject.name` and is done.

**Two fields became correct for free.** `is_compulsory` is a per-exam fact: English is
compulsory in all three boards, but WAEC's *General Mathematics* is compulsory while
JAMB's *Mathematics* is an elective. `full_exam_questions` is also per-exam: JAMB
English is 60 questions; WAEC English Paper 1 is 80. Neither was ever global, and D20
had them wrong as one value.

**Resolution is unambiguous** because `questions` already carries both `exam` and
`subject` — the pair resolves to exactly one row.

**Cost:** ~34 subject concepts become ~100–150 rows across three boards (WAEC and NECO
each run ~76 subjects against JAMB's 25). Those rows describe *genuinely different
offerings* — different papers, different topics, different marks — so the duplication
is honest, not redundant.

**⚠ Consequence to keep in mind.** An **unassigned question (`exam: ""`) cannot resolve
its subject.** That is correct behaviour: such a record is incomplete and must not be
servable. The fixture keeps one deliberately (`q_unassigned_civic_001`) to prove the
loader tolerates incomplete records rather than crashing on them.

### 3.1.15 The storage seam (D23/D24) — the bank moves, the code does not

**The rule.** Routes depend on a trait. They never open a file and never write SQL.

```rust
trait QuestionStore {
    fn exams(&self) -> Vec<Exam>;
    fn subjects(&self, exam: &str) -> Vec<Subject>;
    fn subject(&self, exam: &str, slug: &str) -> Option<Subject>;
    fn syllabus(&self, exam: &str, slug: &str) -> Option<Syllabus>;
    fn questions(&self, q: &Query) -> Page<Question>;
    fn question(&self, id: &str) -> Option<Question>;
    fn passages(&self, ids: &[String]) -> Vec<Passage>;
}
```

`JsonStore` today (RAM over `data/*.json`), `TursoStore` later. Injected as
`Arc<dyn QuestionStore>`.

**What "the code will not change" actually requires — five things, not one.** This is
the part that silently breaks if it is not designed for:

1. **Identical types.** Both stores return the D11 constant. Non-negotiable; already true.
2. **Identical ordering.** A JSON slice and a `SQL … LIMIT/OFFSET` must agree on sort
   order, or the same query returns different questions in each store.
3. **Identical paging.** Both must produce D3's envelope — `page`, `total_pages`,
   `total_records` — from the same underlying count. A count taken in RAM must equal
   the count SQL returns.
4. **Identical absence.** D16's rule (*"absence is the signal"*) must hold in both: a
   topic with no questions does not appear, identically.
5. **Identical validation.** Both refuse to start on invalid data. The loader is a
   correctness gate, not a convenience.

If all five hold, the migration is: write `TursoStore`, flip one constructor, ship.

**Two stores, deliberately (D24).**

| Concern | Store now | Store later |
|---|---|---|
| Content (questions, catalog) | `JsonStore` — `data/*.json` | `TursoStore` |
| **API keys** | **`KeyStore` — Turso, day one** | stays Turso |

Keys are mutable operational state: issued, revoked, rate-limited, eventually billed.
The bank is immutable published content. Mixing them would either put **secrets in the
committed constant** or put **public content in the operational store**, and both are
wrong. `TURSO_DB_TOKEN` is already available, so auth does not have to wait on the
content migration.

**API keys are stored as a hash, never as plaintext.** The key is generated, shown to
the holder exactly once, and only `sha256(key)` is persisted; lookup hashes the incoming
header. This is not a "security feature" in D6's sense — it is simply not writing
user-visible credentials to disk in recoverable form.

```sql
CREATE TABLE api_keys (
  id          TEXT PRIMARY KEY,
  key_hash    TEXT NOT NULL UNIQUE,   -- sha256 hex; plaintext is never stored
  label       TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  revoked_at  TEXT                    -- NULL = live
);
-- quota / rate-limit / plan columns are added when billing needs them (D6).
```

### 3.1.6 What deliberately gets NO table

- **`exams`** — 5 values, no mutable attributes. A code constant, not a table. It
  becomes one when an exam needs metadata (active years, current cycle); today that
  is a single env var (`JAMB_SESSION_END`).
- **`subject_exams`** — folded into `subjects.exams`. 34 rows; "subjects in exam X"
  is app-side filtering. A join table would be more portable but buys nothing here.
- **papers, sessions, users, results** — serving/account concerns, not bank content.
  A paper is **assembled at request time** from the constant, never stored.
- **A polymorphic `catalog` table** merging subjects+topics — would save a table name
  but needs a discriminator deciding which column set applies, with the other null.
  Rejected: pays clarity forever for one name.

### 3.1.4 Relationships

```
subjects ──< topics ──< subtopics ──< questions
   │                     │
   └─────────────────────┘
passages ──< questions          (optional, 1:many)
```

`questions` carries the **coarsest** useful FK (`subtopic_id`); `topic`, `subject`
and `exam` are all one join away. Storing only the finest avoids two sources of truth.

### 3.0c D10 — the naming divergence, recorded for later (no action taken)

Direction of truth: **registry ids → Turso → JSON.**

| Store | Accounting | CRK | English |
|---|---|---|---|
| Registry (`subject.rs:42`) — the authority | `Accounting` | `CRK` | `English` |
| Turso `questions.subject` — **already canonical** | `Accounting` | `CRK` | `English` |
| `data/bank/questions.json` — **long-form, to rename later** | `Accounts - Principles of Accounts` | `Christian Religious Knowledge (CRK)` | `English Language` |

Five JSON strings to normalize when D10 is taken up:
`English Language`→`English` · `Accounts - Principles of Accounts`→`Accounting` ·
`Christian Religious Knowledge (CRK)`→`CRK` · `Islamic Religious Knowledge (IRK)`→`IRK` ·
`Literature in English`→`Literature` (the last one resolves via `display_name`, the
other four via `SUBJECT_ALIASES`).

> **Superseded by D20.** `display_name` no longer exists — subjects are renamed to JAMB's
> official naming and the alias table retires with it. The mapping above is kept only
> because it documents what the JSON still contains.

Note this does **not** delete `SUBJECT_ALIASES` — it stays as a shim for *incoming
vendor* rows (Sdash/ALOC), which is its real job.

**The live risk this defers:** once the public API serves from Turso it will emit
`Accounting`, while the app's JSON emits `Accounts - Principles of Accounts` — two
vocabularies for one subject depending on which store answered. That must be closed
before the API is exposed, not before we keep working.

### 3.0b D9 — what the live Turso table actually holds (measured 2026-10-10)

- **68,613 rows**, **34 subjects**, **years 1978–2025** (48 cycles), ~500–3,200 rows/year.
- Schema (no `exam`): `id, subject, year, content, options, answer, explanation, image, content_hash`
  — identical to the test fixture at `crates/server/src/db/questions.rs:441`. This
  orphan table has always been unowned by a migration (see §2.5).
- **Subject strings are already canonical** — `English`, `Accounting`, `CRK`, `IRK`,
  `Literature` — i.e. the `SUBJECTS` registry ids, *not* the JSON's long-form
  spellings (`Accounts - Principles of Accounts`). The two stores disagree on naming;
  the catalog must reconcile them (O1b).
- **The JAMB ratio inverts vs the JSON:**

| | rows | share |
|---|---|---|
| JAMB (25 subjects) | **65,298** | **95.2%** |
| non-JAMB (9 subjects) | 3,315 | 4.8% |

The JSON is 76% JAMB because it is 100 Qs/subject across all 34. The Turso table is
95% JAMB because it is **actual past UTME papers** — which is exactly why it is worth
keeping. `Further Mathematics` (795), `Civic Education` (596), `Marketing` (439),
`Data Processing` (438), `Catering Craft Practice` (358), `Animal Husbandry` (320),
`Office Practice` (195), `Insurance` (143), `Book Keeping` (31) are the only
non-JAMB inventory there.

- **This is additive only**: one new column, plus per-subject `UPDATE`s. No deletes,
  no schema rewrites, no row removal.

### 3.0 D8 — the JAMB / non-JAMB split being written to the bank

**`exam = "JAMB"` (25 subjects, by exact bank spelling):**
English Language · Mathematics · Physics · Chemistry · Biology · Agricultural
Science · Geography · Economics · Government · Commerce ·
Accounts - Principles of Accounts · Christian Religious Knowledge (CRK) ·
Islamic Religious Knowledge (IRK) · Literature in English · History · Arabic ·
Fine Arts · French · Hausa · Igbo · Music · Yoruba · Home Economics ·
Computer Studies · Physical Education

**`exam = ""` (9 subjects — WAEC/NECO, deliberately unresolved):**
Animal Husbandry · Book Keeping · Catering Craft Practice · Civic Education ·
Data Processing · Further Mathematics · Insurance · Marketing · Office Practice

Rationale for leaving the 9 empty rather than labelling them `WAEC`: we have not
verified which of them are WAEC vs NECO, and per D7 we do not guess. `""` means
**"not JAMB, exam not yet decided"** — the honest value until O1b closes.
Note `Physical Education` in the bank maps to JAMB's **Physical & Health
Education** (renamed on JAMB's side); the bank spelling is kept unchanged here and
the rename is catalog-mapping work, not a data edit.

### 3.1 O1 — RESOLVED (research, 2026-10-10): the canonical subject list

**JAMB UTME offers 25 subjects.** English is compulsory; a candidate writes English + 3.

**All 25 already exist in our bank.** The bank is not short of JAMB subjects — it is
short of *registry entries*.

| # | JAMB UTME subject | in bank | in `SUBJECTS` registry | served today |
|---|---|---|---|---|
| 1 | English Language (compulsory) | 249 | ✅ | ✅ |
| 2 | Mathematics | 100 | ✅ | ✅ |
| 3 | Physics | 100 | ✅ | ✅ |
| 4 | Chemistry | 100 | ✅ | ✅ |
| 5 | Biology | 100 | ✅ | ✅ |
| 6 | Agricultural Science | 100 | ✅ | ✅ |
| 7 | Geography | 100 | ✅ | ✅ |
| 8 | Economics | 100 | ✅ | ✅ |
| 9 | Government | 100 | ✅ | ✅ |
| 10 | Commerce | 100 | ✅ | ✅ |
| 11 | Principles of Accounts | 100 | ✅ | ✅ |
| 12 | Christian Religious Studies | 100 | ✅ | ✅ |
| 13 | Islamic Religious Studies | 100 | ✅ | ✅ |
| 14 | Literature in English | 100 | ✅ | ✅ |
| 15 | **History** | 100 | ✅ but `has_bank: false` | ❌ |
| 16 | **Arabic** | 80 | ❌ | ❌ |
| 17 | **Fine Art** | 100 | ❌ | ❌ |
| 18 | **French** | 100 | ❌ | ❌ |
| 19 | **Hausa** | 100 | ❌ | ❌ |
| 20 | **Igbo** | 100 | ❌ | ❌ |
| 21 | **Music** | 82 | ❌ | ❌ |
| 22 | **Yoruba** | 100 | ❌ | ❌ |
| 23 | **Home Economics** | 100 | ❌ | ❌ |
| 24 | **Computer Studies** *(newly added)* | 100 | ❌ | ❌ |
| 25 | **Physical & Health Education** *(newly added)* | 100 | ❌ | ❌ |

**Result: 14 of 25 JAMB subjects served. 11 JAMB subjects — 1,062 questions — are in
the bank and unreachable.** Two of them (**Computer Studies**, **Physical & Health
Education**) are *brand-new* JAMB UTME subjects that competitors do not carry (the
audit records ALOC as lacking Computer entirely) — that is a differentiator, and we
already own 100 questions each.

#### The two flagged subjects are not the same kind of wrong
- **History** — genuinely a JAMB subject, genuinely 100 questions. `has_bank: false`
  is a plain **bug**.
- **Civic Education** — *not* a JAMB UTME subject (WAEC/NECO/SSS). It is in the
  registry flagged `false`, which is **accidentally correct for JAMB** but wrong as
  written: we do hold 100 questions, they just belong to another exam.

### 3.2 O6 — dissolved by the constant (was: two disagreeing topic predicates)

A real bug in the **old** design, recorded so nobody re-introduces its cause.

`matches_topic` (`crates/core/src/syllabus/mod.rs:341`) is documented as *"the single
predicate behind topic filtering"*:

```rust
match q.topic.as_deref() {
    Some(tag) => tag == topic,            // trusts the tag; no catalog check
    None => question_topic(topics, q).as_deref() == Some(topic),
}
```

`TopicIndex::build` (`:369`) disagrees on exactly that case:

```rust
let topic = q.topic.as_deref()
    .and_then(|tag| topic_for_name(topics, tag))   // tag must EXIST in the syllabus
    .or_else(|| question_topic(topics, q));        // else discard it and classify
```

For a question tagged with a name the syllabus does not contain, `matches_topic` answers
**yes** and `TopicIndex` **discards the tag and classifies instead**. `TopicIndex::matches`
even carries a doc comment claiming it *"agrees with `matches_topic` for every question"* —
false in precisely that case.

**Why it is moot:** the cause was **free-text topic tags**. D15/D16 replaced them with
`subtopic_id`, a foreign key. There is no longer a string that can disagree with the
catalog — a question either points at a real subtopic or points at nothing, and both
predicates collapse into one honest join. The bug cannot be expressed.

**Lesson worth keeping:** free text as a *taxonomy key* is what produced this, the 16-vs-34
registry mismatch, and the alias table. That is why D16 makes topic names catalog data.

### 3.2b The other 9 bank subjects are WAEC/NECO, not JAMB

Animal Husbandry, Book Keeping, Catering Craft Practice, Civic Education, Data
Processing, Further Mathematics, Insurance, Marketing, Office Practice — **831
questions**. These are **not waste**: they are WAEC/NECO inventory already paid for,
directly relevant to the paid-API intent (D1/D2). They are correctly excluded from
the JAMB picker — by data, per D1, not by omission.

**Therefore the registry must split into two questions:**
1. Which subjects are JAMB? → the 25 above (data answer: known).
2. What is each subject's `exam` membership? → JAMB / WAEC / NECO / POST-UTME.

### 3.3 Open — need study before deciding

| ID | Question | Why it matters |
|---|---|---|
| ~~**O1**~~ | ~~Canonical subject list + exam ownership~~ | **RESOLVED — see §3.1.** JAMB = 25 subjects, all already in our bank. Remaining: assign `exam` to the 9 non-JAMB subjects. |
| ~~**O1b**~~ | ~~Confirm the 25 JAMB subjects against `efacility.jamb.gov.ng`~~ | **RESOLVED — 25 confirmed.** See §3.1.13. |
| **D20** | ~~Subjects carry JAMB's official name and nothing else. `display_name` is removed.~~ | **SUPERSEDED by D21** | Kept for its *spirit* — no alias table, verbatim from the official board — but its wording ("JAMB's name") is wrong. There is no single JAMB name: the boards genuinely disagree, and JAMB has no name at all for the 9 subjects it does not offer. |
| **D21** | **Subjects are exam-scoped rows.** Each exam has its own row for a subject it offers; `exams[]` is gone, `exam` is a column, and `slug` is the *exam's own* name (`use-of-english` vs `english-language`). A question resolves its subject by the pair `(exam, subject)`. | **PINNED** (user, 2026-10-10) | §3.1.14. Solves the naming problem **without** two names per row — WAEC's *English Language* and JAMB's *Use of English* are two true rows, not one row plus an alias. It also makes two previously-global fields correct: `is_compulsory` (WAEC's *General Mathematics* is compulsory, JAMB's *Mathematics* is elective) and `full_exam_questions` (JAMB English 60, WAEC Paper 1 = 80). Aligns `subjects` with `topics`, which were already exam-scoped. |
| **D22** | **Principle: choose duplication over complexity.** When a normalised alternative saves rows but costs join logic, branching, or consumer-side reasoning — duplicate the row. DB space is cheaper than cognitive load, on our side *and* the consumer's. | **PINNED** (user, 2026-10-10) | *"duplication on db wont cost much than the other way around."* Retrospective defence of earlier calls: the per-field alias table, D17's rejection of a block enum, and D21 itself. Applies whenever the trade is **rows vs logic**, never rows vs correctness. |
| **D23** | **The bank lives behind a store trait. Routes never touch storage directly.** `JsonStore` (RAM over `data/*.json`) today, `TursoStore` later — **route code does not change when the DB arrives.** `data/` JSON is a **development** store, not the plan. | **PINNED** (user, 2026-10-10) | *"our code should not change once db comes in on that… the json is mainly for dev purpose."* §3.1.15. The bank moves to the DB **little by little**, once the implementation is strong — so the seam has to be real, not aspirational. |
| **D24** | **Two stores, not one.** Content (questions/catalog) → `QuestionStore` (JSON now, Turso later). **API keys → `KeyStore`** — *currently a JSON file outside the constant*; Turso later. Keys are mutable operational state; the bank is immutable published content. | **PINNED** (user), **implementation revised by D28** | Originally "Turso day one". Kept alive by D28. **utmelab-api uses its own separate Turso database** (distinct from UTME-Lab's), which sits empty: the 68k rows are ported from the old DB only during the content migration, not piecemeal. Keys in `data/` would put **secrets in the committed constant**, so the key file lives in gitignored `var/` at 0600. |
| **D28** | **Keys are stored in a local gitignored JSON file today, behind the `KeyStore` shape — not Turso yet.** `libsql` is **dropped**. When Turso is taken up it will be researched against the documented client and added as another impl behind the same shape. | **PINNED** (user, 2026-10-10) | There are **zero customers and one key** — ours. Keys are create/resolve/revoke over one row; a file does that today. Applying D23's own discipline to keys: the seam is what matters, not the backend. Separately, **`libsql` was the wrong dependency** — it compiles SQLite from source (~30 min on a phone) for a service that never runs SQLite locally, and there is a Turso HTTP API we should read the docs for rather than reverse-engineer. Build time went from >25 min to **4 seconds**. |
| **D29** | **Source layout: two surfaces over one core.** `api/` (public commercial API, `/api/v1`, key auth, JSON) and `app/` (dashboard, `/`, human sessions, planned: accounts/usage/billing) sit side by side over `bank/` (domain types, `Store` trait, `JsonStore`, wire views) and `keys/`. **`bank/` contains no HTTP.** `app/` is created now, empty, so nobody's first route lands in `api/` by accident. | **PINNED** (user, 2026-10-10) | Billing arrives with a completely different auth model, rendering and change rate from the API contract we sell. They share the content and nothing else — and the dashboard stays a **module in this binary**, not a second service (one deploy, one process). Keeping `bank/` HTTP-free is what lets both surfaces read it without either reshaping it. `api/v1/` is a directory so v2 is a sibling, not a flag. |
| **D30** | **Paging implemented on the store seam, not in the route.** `Store::questions_page(filter, page, per_page)` returns the page **and** the total, so a Turso impl can push `LIMIT/OFFSET` down without any route changing. Defaults: `per_page` 50, **capped at 200**. Envelope `{ questions, page, per_page, total_pages, total_records }`. | **PINNED** (user, 2026-10-10) | Unbounded responses are a defect, not a missing feature: one `GET /questions?exam=JAMB&subject=english` returned ~4,370 questions in a single payload. Putting the slice **in the route** would have frozen the count in RAM and made D23's "identical paging" impossible to keep when Turso computes it in SQL. The cap is the reason a caller cannot ask for the whole bank. |
| **D31** | **The OpenAPI spec is derived by `utoipa`, not hand-written.** `#[derive(ToSchema)]` on the types handlers return; `#[utoipa::path]` on each handler. **Our axum router is not replaced** — plain `utoipa`, *not* `utoipa-axum`'s `OpenApiRouter`. | **PINNED** (user, 2026-10-10, after research) | The hand-written spec kept producing bugs the drift test had to catch (`securitySchemes` emitted as `security_schemes`; `"type":"integer"` carrying `"default":"50"`). Derived, that bug class is unrepresentable. **`utoipa-axum` was rejected on purpose**: `OpenApiRouter` fuses the router to the spec (`routes!(…)` *is* the router), which conflicts with D29 — `api/` and `app/` are separate surfaces and the dashboard must exist with no spec at all. **Cost, stated:** utoipa cannot emit `default` on a query parameter, so paging defaults (50 / 1 / false) live in parameter *descriptions* and a test asserts they are stated. |
| **D32** | **The web tier is static files. Forever. No JS runtime on the VPS.** One Rust binary + one directory of files, served by Caddy. `web/` is Astro + Starlight, prerendered; the dashboard is a **static shell** that fetches `/internal/v1/*` from the browser. No adapter, no Node process. | **PINNED** (user, 2026-10-10, "static bro! forever… zero js runtime in vps") | SSR was offered because Astro's docs lead with exactly this case — a mistake: that pattern-matched the framework's flagship example instead of the constraint. **Zero JS runtime settles it.** It also removes the second point of failure (a Node crash no longer takes out anything) and, most importantly, removes a trusted second process holding `/internal/v1` credentials. UX is not the trade: the loading state is already solved. |
| **D33** | **`/internal/*` is browser-reachable, authenticated by session cookie — and unversioned.** It is **not** in the public OpenAPI spec. `/api/v1/*` stays API-key authenticated for external customers. | **PINNED** (user, 2026-10-10) | A consequence of D32, recorded so it is designed for rather than discovered. Scaffolded as an empty module (`src/api/internal.rs`) pending the dashboard's first endpoint. No version prefix: internal callers are us, and versioning is a promise to integrators we do not owe ourselves. Both tiers are same-origin on `api.utmelab.com`, so **no CORS anywhere** — a browser `fetch('/internal/v1/me')` sends its httpOnly cookie automatically. The cost of D32 is that `/internal/v1` must be hardened for the browser: session auth on every route, `SameSite` cookies for CSRF, and it must never appear in the public spec. |
| **D34** | **English first and only. Authored in JSON.** Topics, passages, explanations and questions for English are written into `data/api/*.json` — versioned, reviewable, served immediately. **Nothing is written to the new Turso DB until the content migration.** | **PINNED** (user, 2026-10-10) | The service reads JSON, so Turso-written content would be invisible. New content is *authored* — git shows a passage change, a DB row does not. The 68k port is a batch job that carries already-cleaned English rows across. |
| **D35** | **Novel is its own domain, not part of questions.** `novels`, `novel_chapters`, `novel_characters`, `novel_themes`, `novel_questions` — same service, separate tables and routes. **The novel rotates yearly**, so `year_prescribed` (+ `exam`) is load-bearing. Character types and tested skills come **verbatim from the JAMB Literature syllabus**. | **PINNED** (user, 2026-10-10) | A subject question tests a concept you can reason about; a novel question tests whether you read chapter 7. Different content, different API. Reuses `Option`/`answer`-by-id/`Explanation`/paging/`verified` — the machinery, not a copy. JAMB prescribes plot, setting, themes and characterisation-by-type, so those are the tables. Summaries are always our words, never the book's text. |
| **D36** | **Every novel ships with ≥50 questions, enforced at load.** Below 50 a novel is **withheld from serving** (logged, counted) — not a boot failure. One document per book under `data/novels/`; the directory is the index, dropping a novel is deleting its file, and at most one `featured` per exam. | **PINNED** (user, 2026-10-10) | Incomplete is not corrupt: a 12-question novel must never reach a customer, but it must not stop the service either. Same withheld-not-fatal pattern as D21. The file-per-novel shape means adding, dropping and featuring are file operations, never migrations. |
| **D37** | **Novels are categorized: `english` (Use-of-English reading text) vs `literature` (Literature-in-English prescribed text).** We carry **all English** novels and **recent Literature** only. Stubs hold title + category; everything else waits until we face that novel. | **PINNED** (user, 2026-10-10) | JAMB sets novels in two different papers and consumers filter on that line. Older Lit texts are out of use, so only recent ones earn files. Route-level filtering by category comes when the novels are filled, not before. |
| **D25** | **REST over HTTPS, JSON only.** Three response shapes and no others: bare resource for a single object, D3 envelope for paged collections, **RFC 9457 Problem Details** for errors. No GraphQL, gRPC, sparse fieldsets, XML/CSV, or wrapped-success envelopes. | **PINNED** (user, 2026-10-10) | REST means Python, TypeScript and `curl` all reach the same endpoint with no SDK — that is the whole value proposition for small teams. GraphQL adds a client library and kills HTTP caching; gRPC has no browser story. Problem Details is a real standard, so consumers get `status`/`title`/`type` plus our `code` for free. |
| **D26** | **ONE key type. It works from a server, an app, or `curl` — we never ask.** No `sk_`/`pk_` split. Rate limit is **per-key configuration**, not per key-type. The catalog needs **no key at all**. | **PINNED** (user, 2026-10-10) | The two-type split existed to preserve consumer metering — but a `rate_limit` column already does that, and it cost every consumer a classification decision before their first call. Rejected as a *distinction* defending a *field*. The honest consequence is one documentation line, not a key taxonomy: *"if you embed this key in a client app it can be extracted, and whoever extracts it shares your quota."* |
| **D27** | **What "security" means here.** Now, because keys exist: keys stored hashed (D24), **per-key rate limiting**, CORS scoped to the docs origin, and the answer never in a default payload. Infrastructure, not app code: DDoS/edge, encryption at rest, TLS. Deferred to billing (D6): per-key quotas, usage metering, IP allowlisting. | **PINNED** (user, 2026-10-10) | D6 puts security last **for features**. These three are not features — they are the minimum for keys to exist at all, and they are cheap. `?include=explanation` is a data-exposure decision as much as a design one. |
| **O2** | Does the **public API** expose the bank as-is, or a sanitized/derived shape? | Affects whether `answer`/`explanation` are public fields (free tier?) and drives D6 later. |
| **O3** | Is the **64k Turso table** real, usable, and in scope — or is it dead weight to be dropped? | §2.5: orphan table, no migration, unvalidated per audit. |
| **O4** | Topic model: keep one flat `topic`, or add `subtopic`? | 542 syllabus topics vs 317 bank topics — is syllabus the authority? |
| **O5** | Tiering / what is free vs paid, for the public API? | Referenced by `SUBSCRIPTION_V2_DESIGN` lineage; not yet decided here. |
| ~~**O6**~~ | ~~Two disagreeing topic predicates~~ | **MOOT — dissolved by the constant.** See §3.2. |

---

## 4. Corrections to the pulled audit (research output)

`QUESTION_BANK_AUDIT.md` / `GAPS.md` contain claims the data does not support. Do not
build on these without re-checking:

| Claim | Reality |
|---|---|
| A5: "half the TopicCards hide behind `MIN_TOPIC_QUESTIONS=4`" | **False.** 328/329 bank topics have ≥4 questions. |
| A5: "alias drift (`Accounts - Principles of Accounts` vs `Accounting`) breaks topics" | **Misattributed.** That is a *subject* string, handled by `SUBJECT_ALIASES`. Topic drift is **0%**. |
| A4: "History, Civic Education `has_bank=false`" presented as a data gap | **Registry flag bug** — both have 100 questions each. |
| A1: "222 empty explanations" | **Correct.** |
| C6: "`crates/mobile` empty" | **False** — built (`main.rs`, `net.rs`, `store.rs`). |
| Audit: "image 170 rows" | Image *key* present on 3,193; **170 non-null**. |

---

## 5. Sequencing (proposed — not yet decided)

1. Settle **O1** (canonical subjects + exam ownership) → unblocks D1/D2.
2. Define the **canonical schema constant** (question + catalog rows).
3. Then, and only then, touch data or code.

---

## 6. Explicitly not decided

- **Study notes** — coming up, not yet decided. Not touched here.
- Paging details beyond "simple" (D3).
- Pricing, tiers, auth, rate limits (O5, D6).