# Bank work queue

One queue, newest facts first. Finished items leave the list. The numbers below
were measured on 2026-10-27 from the bank and production databases.

## Bank state

| State | Rows | Note |
|---|---|---|
| deduped | 3054 | 2261 NECO, 793 WAEC |
| catalogued | 182 | all WAEC |
| ready | 90 | |
| rejected | 172 | |

The 49 WAEC agricultural-science rows that used to crash on the blank topic
names can now be tagged. The 2261 NECO rows are parked until production has a
NECO catalog.

## Catalog contract

Tagging can only choose a subtopic that exists under a named topic. Production
must hold:

- every topic has a non-empty name and at least one subtopic;
- every subtopic has a non-empty name and belongs to an existing topic;
- every subject has at least one topic and one subtopic.

`utmelab-db --database prod catalog` checks all of it. Blank names and orphans
are errors and exit 1. Coverage gaps (a subject with no topics, a topic with no
subtopics) are warnings unless `--strict` is passed. The batch workflow runs
the check before every task. A seeder must apply the same rules before it
writes; this check catches what slips through.

### Catalog state

- The two blank WAEC agricultural-science topics are named in production and in
  `data/waec/agricultural-science.json`: `Animal diseases` and `Parasites and
  disease control`. The slugs stay as they are, so existing references hold.
- 321 of the 1145 WAEC topics have no subtopics (28%). The largest gaps are
  general-mathematics 40, office-practice 39, book-keeping 39, biology 27,
  economics 25. Their names are syllabus fragments (`1. Resources to be
  conserved: soil, water,`, `2. Ecological factors:`), so this looks like a
  parse that produced headings without children, not 321 independent content
  gaps. Re-importing the WAEC syllabus is the real repair; hand-writing 321
  subtopics would preserve the damage.
- All 36 NECO subjects exist with zero topics. That is the parked NECO work.

## Now

1. **Process the WAEC runway.** 793 deduped WAEC rows through
   `tag -> media -> explain -> review -> ready` in batches of about 200.
   Tagging alone is roughly 20s per row on the opencode route. Run the catalog
   check first, then watch the `ready` count.
2. **Re-import the WAEC syllabus.** Fix the importer that produced the 321
   parent-only topics, then reseed and run `utmelab-db --database prod catalog`
   until the warnings are gone.

## Parked

- **NECO.** 2261 deduped rows cannot be tagged. Production has 36 NECO
  subjects and zero topics and subtopics. The bank never writes production
  (decision D8), so this needs a catalog seeded outside the bank.

## Tools

- **Separate read-only database CLI.** `utmelab-db` is its own command, not
  part of the pipeline CLI. It reads `.env` through `load_settings`, so no
  token is ever passed on a command line or pasted into a terminal. Complex
  work imports `utmelab_bank.db` instead of writing a Turso connection.
  `utmelab-db --database prod catalog` is the catalog health check.
- **Toolchain.** Python 3.14, in `.python-version`, `pyproject.toml` and the
  workflows. The local venv is `.venv`; use `.venv/bin/utmelab-bank` and
  `.venv/bin/utmelab-db`.
