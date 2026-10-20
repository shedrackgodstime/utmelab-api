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
  is_compulsory INTEGER NOT NULL, objective_paper_questions INTEGER,
  PRIMARY KEY (slug, exam)
);
CREATE TABLE exams(
  code TEXT PRIMARY KEY, name TEXT NOT NULL,
  countries TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL,
  has_full_paper INTEGER, subjects_required INTEGER,
  duration_minutes INTEGER, rules TEXT NOT NULL DEFAULT '[]'
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
CREATE TABLE countries(
  code TEXT PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE topic_countries(
  topic TEXT NOT NULL, country TEXT NOT NULL,
  PRIMARY KEY (topic, country)
);
CREATE TABLE exam_requirements(
  exam TEXT NOT NULL, country TEXT NOT NULL, "group" TEXT NOT NULL,
  min_select INTEGER NOT NULL, subjects TEXT NOT NULL DEFAULT '[]'
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

## Phase 1 record (2026-10-13, re-seeded 2026-10-14)

`verifications` seeded: 393/393 rows, per-row `content_hash` equal both
sides (PARITY OK). Rule until the TursoStore read path lands: **the file
stays source of truth; the table is a warm standby re-seeded idempotently
(upsert by id) whenever the file moves** — never dual-written, never
diverged. Seed procedure: one-off Rust example over `turso_serverless`
(read file → upsert → count + hash parity); the DDL stays pinned above.

Re-seed 2026-10-14 (`examples/seed_verifications.rs`, committed): file grew
393 → 2,259 rows through the review rewrite; table re-seeded idempotently,
PARITY OK 2259/2259 rows, 0 hash mismatches. Retry-with-backoff added after
a transient wire drop mid-run (upserts idempotent, resumed cleanly).
`verifications` also registered in `audit-db` (R4; missing table counts 0).

## Phase 2 record (2026-10-14)

`questions` seeded: 2246/2246 servable rows, per-row `content_hash`
recomputed from table columns equal to the file fingerprint (PARITY OK).
Seed: `examples/seed_questions.rs` (committed) — loads via `JsonStore`
so the full fail-closed validation is the write gate (R4), upserts by id
with `content_hash` from the shared `content_fingerprint` (R6), rebuilds
each row from table columns into the same structs and recompares (R1).
The 1 withheld fixture (`exam=""`) is excluded by construction
(`store.questions()` is the servable view); it stays file-side until the
TursoStore read path implements partition itself. File stays source;
table warm standby. `questions` registered in `audit-db`.

## Phase 3 record (2026-10-14)

`passages` seeded: 6/6 rows, all fields equal (PARITY OK) via
`examples/seed_passages.rs`. Novels seeded via `examples/seed_novels.rs`:
6 docs (5 stubs migrate as ordinary rows; the ≥50q serving rule moves to
the read path), 12 chapters, 35 characters, 6 themes, 220 questions —
counts equal all tables, per-row `content_hash` recomputed from table
columns equal (PARITY OK 220/220). Both examples load via `JsonStore`
first so the fail-closed validation is the write gate (R4); the novel
docs are read from disk because `load()` retains only ≥50q novels for
serving while validation covers all 6. All six tables registered in
`audit-db`. Files stay source; tables warm standby.

## Phase 4 record (2026-10-14)

Catalog + blueprints seeded via `examples/seed_catalog.rs`: subjects 34,
exams 4, topics 582, subtopics 2156, countries 5, topic_countries 0,
exam_requirements 2, blueprints 80 — counts equal all 8 tables (PARITY OK).
`JsonStore::load` first as the R4 write gate; PK tables upsert by key,
keyless tables rebuild wholesale (slow-moving, single writer — documented
draft). Foundation fix in the same pass: a stale pre-pinned `subjects`
table was found live (empty, carried `full_exam_questions` instead of the
pinned `objective_paper_questions`); the seed drops + rebuilds all 8
catalog tables, and the re-read DDL confirms the pinned shape. All 14
content tables registered in `audit-db`. With this the pinned DDL is fully
landed: every JSON file has its table. Files stay source until the
TursoStore read path lands; JSON dumps remain as export/backup (R8).

## Read-path record (2026-10-14)

`src/bank/turso_store.rs`: `TursoStore::open` loads all 14 tables and
builds through the shared `JsonStore::from_parts` pipeline (new) — one
pipeline, zero serving-logic duplication. Every `Store` method delegates
to the inner store, so paging/absence/D16/D21/D57 semantics are identical
by construction. Cutover switch: `UTMELAB_BANK_STORE=turso` (default
`json`, current behavior); the Turso branch fails closed like files.
`tests/turso_parity.rs` (env-gated) proves R8 dual-run: counts, pages
(ids+verified+hashes), filtered pages, all syllabus summaries, spot rows,
novels, passage — identical. Known gaps: withheld fixture file-side
(`/health` differs by that 1 row, asserted); `version()` is a count-hash
(R7 row-hash lands with cutover).

## Serving record (2026-10-14) — Turso-only, hot reload, disk cache
Turso is the only source; JSON is dev-only; there is no fallback (a
future Turso mirror is the fallback, not now). `serve` boots
`TursoStore::open_cached`: cheap count-hash version first, `var/`
snapshot on hit, full fetch + cache rewrite on miss. Serving is from
memory either way, so request speed equals the file era. A refresh task
(`UTMELAB_BANK_REFRESH_SECS`, default 300) re-checks the version and
atomically swaps the whole bank (`watch` channel — handlers snapshot an
`Arc`, no locks across awaits), so content changes land with no rebuild
and no restart. Cache failures fall through to fetch; refresh failures
keep the old bank; validation failures never swap in. `AppState.bank` is
a `watch::Receiver`; all route call sites snapshot at handler start.
`tests/bank_cache.rs` (env-gated) proves miss-then-hit serve identical
banks. `UTMELAB_BANK_STORE` switch removed with the JSON branch.

## Version record (2026-10-14) — R7 row-hash landed

`version()` is now a 16-hex SHA over ordered row content across all 14
tables: id + stored `content_hash` where the table carries it (questions,
verifications, novel_questions — the same fingerprint review trusts),
full row content everywhere else, NULLs distinct from empty strings,
fixed column order. Any edit that changes what is served changes the
version, so the refresh loop can no longer miss a count-preserving edit
(the count-hash draft could). Determinism proven by `bank_cache`
(miss/hit identical); cross-source equality with the file fingerprint is
still not claimed — consumers compare within a source. Retries hardened
in the same pass: `all()` retries idempotent reads, `current_version`
retries, boot retries `open_cached` (validation still fails closed, so
retries can only boot a good bank).

## Writer record W1 (2026-10-14) — `verify` CLI writes Turso

Production verifications go through `cargo run -- verify --id <qid>
--by <who>`, not file appends: same gates as review (flags clear via
`quarantine::scan` generalized to `&dyn Store`, explanation present,
already-verified short-circuit), ISO-UTC timestamps matching the file
convention (civil-date math, unit-tested vectors), collision-free row
ids (count + bump-while-taken; upsert deliberately NOT used — a clash
retries, never silently overwrites). Write order is **file first, Turso
second**: any gap heals on the next idempotent re-seed; the reverse
would leave twins nothing heals. `review.py` is untouched (dev/scratch
triage; its file appends converge via re-seed). Live-proven gates:
already-verified short-circuit + option_count refusal; the full write
path awaits its first real (non-parked, eligible) row — the bank is
complete, so none exists today.

## Writer record W2 (2026-10-14) — `import --turso` writes the source

`cargo run -- import --turso [--dry-run]`: the admission core
(`admit()`: files loop, per-row gates, catalog check, id/dup checks) is
sink-agnostic over `&dyn Store`; the file path is byte-for-byte unchanged
(dev default), the Turso path runs `check_new_questions` (full
whole-bank validation on the merged bank) and refuses on any problem,
then upserts admitted rows with shared fingerprints (`bank::write`).
D58 carry-through stays file-side (Turso holds servable rows only).
Live-proven dry-run against prod Turso (staged lekki file correctly
refused on subject slug); R4 refusal power unit-tested (unknown subject
fails the gate). `review.py`/harvester untouched (inbox producers).

## Withheld record (2026-10-14) — last file-side row moved

`q_unassigned_civic_001` (`exam=""`) seeded like every other row; the
read path partitions it through the shared pipeline, so
`withheld_count` now matches file-side exactly (parity test asserts
equality, fudge removed). No file holds live bank data that Turso
lacks. `data/` remains for dev (inbox, drafts, backups) + export.
