# WAEC Subject Catalog Alignment & Source Check Plan

Date: 2026-10-29
Status: PLANNED — not yet implemented

---

## Context

The production database is the single source of truth for subjects, topics, and syllabus. Several prod WAEC subject names/slugs drift from the official WAEC Nigeria names (2026 timetable + approved-subjects list). MySchool source availability has only been probed with ad-hoc queries; a systematic check against the authoritative prod list is needed.

The `subjects.json` refactor (loading catalog from prod, keeping only MySchool mappings) is a **separate architectural plan** — not part of this WAEC alignment.

---

## 1. Prod DB Updates — WAEC Subject Names & Slugs to Official

The prod `subjects` table rows for WAEC must be renamed to match the official WAEC Nigeria names (codes from the registration list, names from the 2026 timetable). Changing slugs requires a cascade update on `topics.subject` FK.

| current slug | current name | → official slug | official name | WAEC code |
|---|---|---|---|---|
| `agricultural-science` | Agricultural Science | `agriculture` | Agriculture | 502 |
| `animal-husbandry` | Animal Husbandry | `livestock-farming` | Livestock Farming | SC518 |
| `financial-accounting` | Financial Accounting | `accounting` | Accounting | 104 |
| `visual-arts` | Visual Arts | `visual-art` | Visual Art | 706 |
| `health-education` | Health Education | (keep) | Health Education / Health Science | 508 |
| `literature-in-english` | Literature-in-English | (keep) | Literature-In-English | 210 |

**Missing subjects to add** (from 2026 timetable/entry regulations):

| official slug | official name | WAEC code | countries |
|---|---|---|---|
| `arabic` | Arabic | 301 | ["NG"] |
| `beauty-and-cosmetology` | Beauty & Cosmetology | — | ["NG"] |
| `computer-hardware-and-gsm-repairs` | Computer Hardware and GSM Repairs | — | ["NG"] |
| `fashion-design-and-garment-making` | Fashion Design & Garment Making | — | ["NG"] |
| `solar-photovoltaic-installation-and-maintenance` | Solar Photovoltaic Installation and Maintenance | — | ["NG"] |
| `livestock-farming` | Livestock Farming | SC518 | ["NG"] |
| `citizenship-and-heritage-studies` | Citizenship and Heritage Studies Education | — | ["NG"] *(from 2028)* |
| `digital-technologies` | Digital Technologies | — | ["NG"] *(from 2028)* |
| `horticulture-and-crop-production` | Horticulture and Crop Production | — | ["NG"] |

**Prod-only subjects not on 2026 timetable** — keep for now (examined in earlier years):
- `book-keeping`
- `computer-studies`
- `data-processing`
- `insurance`
- `office-practice`

---

## 2. Strict Source Check (Immediate Objective)

Iterate **all current prod WAEC subjects** (the 36 rows) and verify MySchool availability using the **current** `subjects.json` mappings as the baseline. This produces a baseline before any prod changes.

### Procedure
1. Load prod WAEC subjects: `SELECT slug, name FROM subjects WHERE exam='WAEC'`
2. For each subject, look up MySchool source slug from current `subjects.json` WAEC mapping.
3. Probe MySchool API for each year 2022–2025:
   ```
   GET https://myschool.ng/api/web/v1/classroom/{source_slug}?exam_type=waec&exam_year={year}&page=1
   ```
4. Record:
   - HTTP status
   - `practice_questions.total`
   - `practice_questions.last_page`
   - Whether `practice_questions.data` is non-empty on page 1
5. Output table:
   | prod_slug | prod_name | myschool_source_slug | 2022_total | 2023_total | 2024_total | 2025_total | status | notes |

### Expected outcomes
- Confirm which subjects have data on MySchool.
- Identify any subject where the current mapping is wrong (source slug returns 404/0 but a different slug has data).
- Produce a CSV/JSON artifact for the next decision.

---

## 3. Implementation Order

1. **Run strict source check now** (uses current prod + current `subjects.json`).
2. **Extend `utmelab-db` CLI** to allow prod writes (UPDATE with FK cascade) — safety-gated, transactional, dry-run by default.
3. **Apply prod subject updates** (slug + name changes, missing inserts) in one transaction.
4. **Re-run strict source check** against updated prod to confirm.

---

## 4. Safety Guards for Prod Writes

- CLI command: `utmelab-db --database prod migrate --apply` (default = dry-run, prints SQL).
- Single transaction: update `subjects` + update `topics.subject` FK + insert new rows.
- Pre-flight: print affected row counts, show diff.
- Post-flight: verify row counts, spot-check a few topic slugs.
- No prod write without explicit `--apply` and a confirmation prompt.

---

## 5. Files to Touch

| file | change |
|---|---|
| `docs/WAEC_SUBJECT_CATALOG_PLAN.md` | this document |
| `utmelab-bank/src/utmelab_bank/cli/db.py` | add `migrate` subcommand with prod write support |
| `scripts/waec_source_check.py` | new script for the strict source check |

---

## 6. Open Questions

- Should the 5 prod-only subjects (`book-keeping`, `computer-studies`, `data-processing`, `insurance`, `office-practice`) be kept, archived, or marked deprecated?
- Do we add the 2028 subjects (`citizenship-and-heritage-studies`, `digital-technologies`) now or wait?
- What is the exact MySchool source slug for `livestock-farming`? (Current mapping uses `animal-husbandry` → MySchool `animal-husbandry`; the official name change may or may not affect the source slug.)

---

## 7. Next Action

**Run the strict source check script** against current prod + current `subjects.json` to produce the baseline availability table. Then review results before any prod writes.