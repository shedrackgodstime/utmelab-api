# Bank work queue

One queue. Measured 2026-10-27 from the bank and production databases.

## Definition of green (NECO parked)

A run is green when all of these hold:

1. `utmelab-db --database prod --strict catalog` reports zero defects and zero
   coverage gaps for JAMB and WAEC. NECO is reported as parked until its
   catalog exists, not as an active warning.
2. Every WAEC topic and subtopic comes from the official PDF. No blank names,
   no orphans, no parent-only topics, no inferred headings.
3. All 871 WAEC deduped rows are `ready`, or `rejected` with a recorded
   reason. No row is stuck.
4. The 137 catalogued, 4 ready and 1 verified WAEC rows still resolve against
   the rebuilt catalog.
5. `cargo check --workspace`, `cargo check -p utmelab-ui --features
   web-pages,server`, `cargo test --workspace`, ruff, mypy and the four
   workflows pass.

NECO is the one exception: 36 subjects with no topics and 2261 deduped rows.
It stays parked until phase 5.

## Measured state

| State | Rows | Note |
|---|---|---|
| deduped | 3135 | 2261 NECO, 871 WAEC, 3 JAMB |
| catalogued | 137 | all WAEC; 5 tagged by Kilo, 132 by OpenCode |
| ready | 53 | 49 JAMB, 4 WAEC |
| rejected | 172 | duplicate_exact / duplicate_near |
| adapted | 4 | JAMB |
| verified | 1 | WAEC |

Production questions: JAMB 2241 (2240 tagged), WAEC 1 (0 tagged). WAEC catalog
churn therefore cannot break a production question today.

Catalog: JAMB 25 subjects / 583 topics / 2158 subtopics; WAEC 36 / 840 /
2892; NECO 36 / 0 / 0. Errors 0. Production warnings are the 36 parked NECO
subjects; the WAEC compiler also reports 38 duplicate topic names, which are
warnings rather than defects.

The WAEC catalog is not a small repair:

| Subject | Topics | Subtopics | Parent-only |
|---|---|---|---|
| general-mathematics | 41 | 1 | 40 |
| economics | 29 | 9 | 25 |
| book-keeping | 50 | 26 | 39 |
| office-practice | 55 | 82 | 39 |
| biology | 45 | 45 | 27 |
| geography | 119 | 148 | 24 |
| computer-studies | 77 | 325 | 17 |
| physics | 43 | 105 | 14 |
| english-language | 10 | 15 | 8 |

Names carry PDF artefacts (`Surds (Radicals) •∗∗ ∗∗ ( k )`, `Positiv e and
nega tive integers`). The importer read the wrong column or level. The HTML
pages repeat some lost headings (`<dt></dt>`) and split prose into fragments,
so they cannot be the source of truth. The official PDF is.

The 36 official PDFs are pinned by URL, byte count, page count and SHA-256 in
`data/waec/sources.json`. The local copies live in `/tmp/opencode/pdfs` during
work and are reproduced by the manifest.

## Plan

### Phase 0 - pin the source (done)

- 36 PDFs downloaded from `waecsyllabus.com`, verified as `%PDF`, hashed.
- `data/waec/sources.json` is the manifest. A subject without a matching hash
  cannot be rebuilt or seeded.

### Phase 1 - catalog compiler

New command `utmelab-catalog`, outside the bank pipeline (D8). It owns the
catalog; the bank only reads it.

Subcommands:

- `fetch` - download and hash-check the PDFs in the manifest.
- `parse` - rebuild `data/waec/<subject>.json` from the PDF.
- `check` - apply the catalog contract to the JSON, before any write.
- `diff` - compare the rebuilt JSON against production.
- `apply` - guarded upsert, one subject at a time.

Parser rules:

- Extract text chunks with x/y, not flat text.
- Detect the topic marker for each subject (`1.`, `1.0`, `(a)`, ...) and the
  subtopic marker (`(a)`, `(i)`, `1.1`, `-`).
- Where the subtopics live in a second column, assign right-column blocks to
  the topic whose y-range contains them.
- If a topic has prose and no marker, split at sentence boundaries. Never
  synthesize or reword text.
- Fail closed: a topic with no subtopic, an empty name, an unmatched string, or
  a count that disagrees with the PDF stops the subject.

Build order:

1. economics, office-practice, general-mathematics (the worst and in the
   queue).
2. the other queue subjects: english-language, government, physics,
   computer-studies, christian-religious-studies, civic-education, geography,
   agricultural-science, commerce, further-mathematics, data-processing,
   literature-in-english, marketing, islamic-studies, yoruba.
3. the rest, until all 36 pass `check`.

Exit: 36 rebuilt JSON files, `utmelab-catalog check --all` zero defects, and a
diff report that explains every removal and rename.

### Phase 2 - reseed

- `diff` prints inserts, updates and deletes per subject.
- Refuse to delete a subtopic referenced by a question. Today that is zero
  WAEC rows, so the first reseed is unconstrained.
- Preserve a slug when the topic order and normalised name match; give new
  rows deterministic slugs.
- Apply one subject at a time, then `utmelab-db --database prod catalog`.
- Re-tag the few bank rows whose snapshot subtopic disappears; the rest keep
  their tags.

### Phase 3 - the 871 WAEC rows

- Run `tag -> media -> explain -> review -> ready` in batches of about 200,
  scoped by subject, starting with subjects whose catalog just passed.
- Watch `ready`, `stopped` and failures. Content rejections do not count
  toward the failure cap; provider, database and media failures do.
- Sentence-level tags must resolve to a subtopic that exists. A row with no
  possible subtopic is rejected with a reason, never guessed.
- The tag and explain routes now ask the Kilo CLI first (`kilo/kilo-auto/free`),
  because its free tier answers with no credential at all: proven on an
  `ubuntu-latest` runner, 3/3 catalog-bound tags, no `auth.json` before or
  after. `config/providers/kilo.json` records the measurements.
- Measure the pass rate on a real batch before scaling. In the local sample the
  auto router tagged 14/20 rows and the pinned Nemotron route 16/20; the
  misses were mostly low-confidence abstentions, which a second pass retries
  against a different free upstream model.
- A missing CLI is `provider_unavailable`, not a hard failure, so `config`
  falls through to OpenCode on a machine that has not installed Kilo.

### Phase 3a - the mock is gone (done 2026-10-27)

The mock provider always tagged `catalog.subtopics[0]`, so every row it touched
carried an arbitrary placement: 60 `catalogued` and 38 `ready` WAEC rows, plus
3 `ready` JAMB rows. All 101 were reset to `deduped` with the placement
cleared; zero mock tags remain anywhere in the bank.

The cause was that the double was selectable from the product: `--provider
mock` reached `create_text_provider`, and its proposal passed every downstream
gate because it was structurally valid. It now lives in `tests/fakes/` only.
`create_text_provider` refuses it, the CLI no longer offers it, and the media
describer no longer builds two mock witnesses that agree with each other.

### Phase 4 - media

Current bank has no rows waiting at media; all 66 historical media failures
ended in `rejected`. The latent gap is `create_configured_describer()` using
`routes[:2]` and `DescribeImageConsensus` failing closed. Fix it before media
is enabled for new rows: use every configured route, or make the policy
explicit (two witnesses from the full pool, with a named failure).

### Phase 5 - NECO (the only path to global strict)

- Seed the 36 NECO subjects from the NECO syllabus source.
- Then process 2261 deduped rows.
- Until then the health check reports NECO as parked, and `--strict` is scoped
  to JAMB + WAEC.

## Paused

- No bank batch and no production catalog write until phase 1 passes `check`
  and the diff is reviewed. This prevents tagging 871 rows against a catalog
  that is about to change.

## Tools

- **Separate read-only database CLI.** `utmelab-db` is its own command. It
  reads `.env` through `load_settings`, so no token is passed on a command
  line. `utmelab-db --database prod catalog` is the health check.
- **Separate catalog CLI.** `utmelab-catalog` is the only writer. It reads the
  full token from `.env`, never prints it, and refuses to delete referenced
  rows.
- **Toolchain.** Python 3.14 in `.python-version`, `pyproject.toml` and the
  workflows. Use `.venv/bin/utmelab-bank`, `.venv/bin/utmelab-db` and
  `.venv/bin/utmelab-catalog`.
