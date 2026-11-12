# The bank pipeline: what is fixed, and the one thing that is not

Status: Active
Last updated: 2026-11-12

The content bank is the only source of real past papers. The pipeline that
fills it was blocked. Here is what was wrong, what is fixed, and the single
action left.

## What was wrong

**The environment.** The bank's virtualenv was built before the repository
moved. Its shebang still pointed at the old path, the editable install still
pointed at the old path, and two dependencies were missing.

Repaired, in `utmelab-bank/`:

```bash
printf '%s\n' "$PWD/src" > .venv/lib/python3.14/site-packages/_editable_impl_utmelab_bank.pth
uv pip install --python .venv/bin/python3 "lxml>=5,<7" "turso-serverless>=0.1"
```

The CLI runs again:

```
$ .venv/bin/python3 -m utmelab_bank tasks
tasks:
  fetch      Scrape one scope, gate it, capture figures, and stop at deduped.
  capture    Capture figures for deduped rows that still need media.
  tag        Place deduped rows in the catalog.
  media      Describe captured figures with two witnesses.
  explain    Write the explanation and enrich the row.
  review     Check the answer and record the verification.
  ready      Check the ready conditions and promote the bundle.
  index      Reload the production half of the content index.
  index-sync Sync bank index with staging (remove orphans, re-index missing).
  status     Report counts per state and index size.
```

**The source works.** A read only probe of MySchool, the source the bank
scrapes, shows it carries far more than we hold:

| Exam | Subject | Questions on the source, 2014 to 2025 |
| --- | --- | --- |
| JAMB | Physics | 806 |
| JAMB | Mathematics | 651 |
| JAMB | English | 1395 |
| JAMB | Chemistry | 824 |
| JAMB | Biology | 820 |
| WAEC | Physics | 763 |
| WAEC | Mathematics | 779 |
| WAEC | English | 1644 |
| WAEC | Chemistry | 692 |
| WAEC | Biology | 692 |
| NECO | Physics | 322 distinct, the same set for every year |
| NECO | Mathematics | 179 distinct, the same set for every year |
| NECO | English | 271 distinct, the same set for every year |

Our bank holds 105 JAMB physics questions and 100 WAEC physics questions. The
source carries about eight times that. The census is in
`data/coverage/source-census.json`, and the probe is
`scripts/source_census.py` in this repository.

NECO reports the same count for every year, so the endpoint ignores the year
there. Those are distinct question sets, not twelve copies.

## The one thing that is not fixed

The bank's own staging database refuses reads on the current plan:

```
Operation was blocked: SQL read operations are forbidden
(reads are blocked, do you need an upgrade to your plan?)
```

It is not the code, and it is not the token. A probe shows exactly where the
boundary sits:

| Operation on the bank database | Result |
| --- | --- |
| `CREATE TABLE` | works |
| `INSERT` | works |
| `SELECT` | blocked by the plan |

The pipeline reads its own index for the dedupe step and for the status
report, so it stops at the first query:

```
$ .venv/bin/python3 -m utmelab_bank fetch --exam JAMB --subject physics --year 2025 --source myschool --limit 2
error: query failed: Operation was blocked: SQL read operations are forbidden ...
```

The production catalogue reads fine. Only the bank's staging database is
closed.

**What actually happened**: the group's monthly read quota ran out. The
block is not a setting to toggle, it is a bill. Reads of the bank database
were metered, the pipeline ran a great many of them, and the month ended
with the quota spent. The group is down until the quota resets or the plan
is raised.

Two things follow.

**Nothing in the repository needs to change.** The probe above confirms the
only thing in the way is the exhausted quota.

**The production catalogue is on the same meter.** It has been read by the
API's sync, by our own tooling and by the source census. The rule from now
on: the catalogue is read sparingly and the answers are cached, never
re-read on every run.

`scripts/link_bank.py` now keeps its answers in `data/staging/bank-papers.json`
and only reads the catalogue when a link is missing from the cache or when
`--refresh` is passed. It prints how many reads it made. The source census
is a separate, deliberate probe, not something to run on a loop.

## What happens the moment it is unlocked

```bash
cd utmelab-bank
.venv/bin/python3 -m utmelab_bank fetch --exam JAMB --subject physics --year 2025 --source myschool
.venv/bin/python3 -m utmelab_bank fetch --exam WAEC --subject physics --year 2025 --source myschool
# and the same for the years the source carries, then the process preset:
.venv/bin/python3 -m utmelab_bank process
```

Every scope that lands fills the empty exam links in the chapter specs, the
packs gain their past papers, and the candidate traps can be promoted from
candidate to proven as their evidence arrives.

## What we will not do

We will not write to the production catalogue to work around this. The bank
exists to gate content before it is served, and staging unvetted rows in the
catalogue the API reads would undo the only quality control we have.
