# DB schema — where every JSON file goes (D64)

**Status:** pinned 2026-10-13, **not implemented**. Nothing serves from Turso
except keys (D53, done). This file is the target every clearing phase moves
toward; the decision log (D64) is the law.

**Rule of the move:** the DB stores the *same structs* the API serves today.
Scalar columns carry everything filtered, sorted or counted; JSON columns
carry the nested shapes byte-for-byte (same serde). That makes D23's
"identical types" true by construction instead of by discipline. Per D22,
options and marks stay JSON blobs — a table per mark would buy nothing and
cost every read a join.

> **Supersedes two comments:** `store.rs` ("novels … never move to a
> database", "the directory is the index") and the embedded-catalog
> transitional notes. File-per-doc indexing retires when its table lands;
> until then those comments describe the present, not the law.

---

## DDL (Turso / SQLite)

```sql
-- Phase 1: verification log (small, append-only, high churn with review)
CREATE TABLE verifications(
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,     -- no FK: covers bank AND novel ids
  kind TEXT NOT NULL,            -- human | ai_single | ai_bulk | auto_rule
  verdict TEXT NOT NULL,         -- pass | fail
  scope TEXT NOT NULL DEFAULT '[]',   -- JSON ["answer","explanation",...]
  verifier TEXT NOT NULL,
  detail TEXT,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_ver_q ON verifications(question_id, created_at);

-- Phase 2: the bank (bulk-seeded from questions.json, hash backfilled)
CREATE TABLE questions(
  id TEXT PRIMARY KEY,
  exam TEXT NOT NULL,            -- '' = withheld, never servable (D21)
  subject TEXT NOT NULL,
  year INTEGER NOT NULL,         -- cohort prepared for (D52)
  source TEXT NOT NULL,          -- past_paper | claimed_paper | authored | imported
  text TEXT NOT NULL,            -- RichText.text, plain (?q= runs here)
  inline TEXT NOT NULL DEFAULT '[]',  -- RichText.inline JSON
  options TEXT NOT NULL,         -- JSON [{id, text:{text,inline}}]
  answer TEXT NOT NULL,          -- option id, never label/index (D15)
  subtopic_id TEXT,
  section TEXT,
  passage_id TEXT,
  explanation TEXT,              -- JSON {key_point,body,trap?} or NULL
  marks REAL NOT NULL,
  difficulty INTEGER NOT NULL,
  content_hash TEXT NOT NULL     -- maintained on write, never authored
);
CREATE INDEX idx_q_exam_subject ON questions(exam, subject);
CREATE INDEX idx_q_subtopic ON questions(subtopic_id);
CREATE INDEX idx_q_source ON questions(source);
CREATE INDEX idx_q_year ON questions(year);

-- Phase 3a: passages (small, stable)
CREATE TABLE passages(
  id TEXT PRIMARY KEY,
  exam TEXT NOT NULL, subject TEXT NOT NULL, year INTEGER NOT NULL,
  kind TEXT NOT NULL, title TEXT, author TEXT,
  text TEXT NOT NULL, inline TEXT NOT NULL DEFAULT '[]'
);

-- Phase 3b: novels (one doc becomes nine tables; directory-index retires)
CREATE TABLE novels(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL,
  year_published INTEGER, exam TEXT NOT NULL,
  year_prescribed TEXT NOT NULL DEFAULT '[]',
  category TEXT NOT NULL DEFAULT 'english', featured INTEGER NOT NULL DEFAULT 0,
  synopsis TEXT NOT NULL, setting_place TEXT NOT NULL,
  setting_period TEXT NOT NULL, cover_image TEXT
);
CREATE TABLE novel_chapters(
  novel_id TEXT NOT NULL, number INTEGER NOT NULL, title TEXT NOT NULL,
  summary TEXT, key_events TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (novel_id, number)
);
CREATE TABLE novel_characters(
  novel_id TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
  character_type TEXT NOT NULL, description TEXT NOT NULL,
  PRIMARY KEY (novel_id, name)
);
CREATE TABLE novel_themes(
  novel_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL,
  evidence TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (novel_id, name)
);
CREATE TABLE novel_questions(
  id TEXT PRIMARY KEY, novel_id TEXT NOT NULL, chapter_number INTEGER,
  text TEXT NOT NULL, inline TEXT NOT NULL DEFAULT '[]',
  options TEXT NOT NULL, answer TEXT NOT NULL, explanation TEXT,
  content_hash TEXT NOT NULL
);

-- Phase 4: catalog + blueprints (slow-moving; embedded until then, then the
-- include_str! lines delete and the binary shrinks to code)
CREATE TABLE subjects(
  slug TEXT NOT NULL, exam TEXT NOT NULL, name TEXT NOT NULL,
  is_compulsory INTEGER NOT NULL, full_exam_questions INTEGER NOT NULL,
  PRIMARY KEY (slug, exam)
);
CREATE TABLE topics(
  slug TEXT PRIMARY KEY, subject TEXT NOT NULL, exam TEXT NOT NULL,
  name TEXT NOT NULL, "order" INTEGER NOT NULL,
  weight INTEGER NOT NULL DEFAULT 0,          -- 0 = not published (D50)
  objectives TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE subtopics(
  slug TEXT PRIMARY KEY, topic TEXT NOT NULL, name TEXT NOT NULL,
  "order" INTEGER NOT NULL, objectives TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE blueprints(
  exam TEXT NOT NULL, subject TEXT NOT NULL, level TEXT NOT NULL,
  topic TEXT, section TEXT, members TEXT NOT NULL DEFAULT '[]',
  paper_size INTEGER NOT NULL,
  pct REAL, pct_low REAL, pct_high REAL,
  expected REAL, expected_low REAL, expected_high REAL,
  source TEXT, sample TEXT, method TEXT NOT NULL, confidence TEXT,
  status TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
);
```

(`"order"` is quoted: bare `order` collides with `ORDER BY`.)

## Read/write rules (pinned with the schema)

* **R1 — same structs.** JSON columns deserialize into today's `RichText`,
  `Choice`, `Explanation`. No parallel DB types, ever.
* **R2 — same paging.** `ORDER BY id`, `LIMIT/OFFSET` + `COUNT(*)` into the D3
  envelope; the 200 cap stays in Rust, not SQL.
* **R3 — same absence.** Topics with zero questions don't appear (D16), in
  both stores, computed the same way.
* **R4 — validation moves to write time.** No boot-load exists for a DB, so
  import/review/migration enforce the same Rust predicates before writing,
  plus a `cargo run -- audit-db` read-time checker. Invalid data never lands;
  audit proves it regularly.
* **R5 — verified derives at read, in Rust.** Page rows + one batched
  `verifications WHERE question_id IN (...)` query, then the shared
  `human_verified()` — the tested logic, not a SQL duplicate. Never a stored
  flag.
* **R6 — `content_hash` maintained on every write** by the shared
  fingerprint fn (import, review, migration, and the Turso writer).
* **R7 — version unchanged in contract.** 16-hex sha over ordered row hashes
  + catalog + novels + log (D42); consumers compare strings, nothing else.
* **R8 — dual-run per phase.** Table serves alongside its file with
  count-parity + spot-checks; the file deletes only after parity holds. JSON
  dumps remain forever as export/backup, just not as source.
* **R9 — what never moves.** `data/inbox/` (staging, always files),
  `var/reports.json` (operational; its table arrives with the dashboard).

## Clearing order

keys ✅ (D53, live) → verifications → questions → passages + novels →
catalog + blueprints → binary is code only. One phase per commit; a phase
lands only with parity proof in its message.

## Phase 1 record (2026-10-13)

`verifications` seeded: 393/393 rows, per-row `content_hash` equal both
sides (PARITY OK). Rule until the TursoStore read path lands: **the file
stays source of truth; the table is a warm standby re-seeded idempotently
(upsert by id) whenever the file moves** — never dual-written, never
diverged. Seed procedure: one-off Rust example over `turso_serverless`
(read file → upsert → count + hash parity); the DDL stays pinned above.
