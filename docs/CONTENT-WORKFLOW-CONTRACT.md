# Content Workflow Contract

Status: Active  
Last updated: 2026-11-10  

This document defines the required process, artifacts, and definition of done for adding/updating content (concepts, syllabus mappings, placements, and study notes) for any subject/exam. Follow it strictly.

## Core Principles
- **No invention**: Never invent facts, figures, examples, answers, figures, tables, media, or exercises. Only restructure content from reliable sources.
- **Provenance required**: Every sourced concept must have `source_attribution` with `publisher/book/section/url/licence` and a concrete `locator` (section, unit, module, page range, figure/table, or article section).
- **Licence/status recorded**: If licence is uncertain or review-pending, record `licence`/status honestly in the concept, audit, and source tables. Do not guess.
- **Source of truth**: The syllabus/catalog mapping lives in `data/concepts/audit-<scope>.json` (e.g. `audit-nonscience.json`). Concepts live in `data/concepts/*.json` (gitignored local staging). Production catalog snapshot lives in `data/prod-catalog-subtopics.json` (gitignored).
- **Validation first**: Changes must pass validators before being considered done.

## Artifacts Required Per Subject
| Artifact | Location | Notes |
| --- | --- | --- |
| Audit mapping | `data/concepts/audit-*.json` | Per topic/subtopic with status (`covered`/`thin`/`no_source`), concept IDs, notes, subtopics list. Update when coverage changes. |
| Coverage audit doc | `docs/*COVERAGE-AUDIT*.md` | Narrative + matrices, sources/licence tables, gaps. Keep in sync with audit. |
| Concepts | `data/concepts/<concept_id>.json` | One JSON per concept (schema v4). Gitignored. |
| Production catalog snapshot | `data/prod-catalog-subtopics.json` | Authoritative `topics`/`subtopics` slugs from production (read-only fetch). Refresh if catalog changes. |
| Placements | In each concept's `placements[]` | Must match production identifiers exactly. |
| Study notes (prod-format) | `data/generated-notes/prod-topic-notes-*.json` | One canonical note per production placement (synthesized from concepts). Gitignored until imported. |
| Ingestion manifest | `data/concepts-ingestion-manifest.json` | Per-concept metadata/object keys/placements for upload/import. Update after changes. |

## 1) Concept Contract (Schema v4)
Follow `docs/CONCEPT-DOCUMENT-SCHEMA.md` exactly.

Required fields:
- `concept_id` (stable slug), `schema_version` (4), `updated_at` (ISO 8601 date), `title`, `subject_area`
- `source_attribution` (publisher/book/section/url/licence/locator/notes as needed)
- `revision_summary` (< 16 KiB when serialized as TopicNote): `read_time_minutes`, `key_takeaway` (RichText), `sections[]`, `worked_examples[]`, `formulas[]`, `active_recall_checks[]`, `examiner_traps[]`, `sources[]`
- `deep_context.blocks[]` (ordered blocks with ids/types/levels; RichText/latex as specified)
- `placements[]` (see Placement Contract)

Rules:
- Heading numbers only from `section_number` or block order; no manual numeric prefixes.
- Callout kinds limited to `key_concept`, `examiner_tip`, `warning`, `law`, `definition`.
- Inline offsets are Unicode scalar offsets into owning text.
- No HTML/Markdown stored; use RichText/structured blocks.
- Figures/tables captured where present in source; reference via `figure` blocks or `figure_ref` with assets in `data/concepts/images/` if downloaded.
- If content is derived/application-level, do not invent facts; mark clearly or omit.

Validation: `python3 scripts/validate_concepts.py` must pass with 0 errors.

## 2) Syllabus Mapping & Coverage Contract
1. **Get authoritative syllabus/catalog**: Pull production topics/subtopics for target `(exam, subject)` via `scripts/fetch_prod_subtopics.py` (read-only using `utmelab-bank/.env` creds) into `data/prod-catalog-subtopics.json`.
2. **Map every topic/subtopic**: For each production topic and subtopic, identify sourced concepts that address it. Update `audit-*.json`.
3. **Status assignment**:
   - `covered`: Sourced concepts address the topic/subtopics as required (individual subtopic coverage where production expects subtopics).
   - `thin`: Sourced but some subtopics/objectives not fully matched or depth insufficient. Document in audit notes.
   - `no_source`: No matching reliable source found. Do **not** guess/fill; record explicitly.
4. **Document sources**: Update coverage audit doc with source tables (publisher/title/url/licence/status/locator/concepts).
5. **English-specific**: Ensure all production English subtopics are individually mapped where production uses subtopics (e.g. JAMB use-of-english 12/12, WAEC english-language all production subtopics). Distinguish between separate subjects (e.g. WAEC English Language vs WAEC Literature-in-English) if catalogs differ.

Done when: Audit and coverage doc are consistent, every production topic/subtopic is either mapped to concepts or marked `no_source` with rationale, and no unmapped required items remain without justification.

## 3) Placement Contract
Each concept's `placements[]` must use **exact** production identifiers:
- `exam`, `subject`, `topic_slug`, `subtopic_slug` (string or `null` only if production expects topic-level placement).

Rules:
- Derive from audit mappings, validate against `data/prod-catalog-subtopics.json`.
- Prefer individual subtopic placements when production has subtopics and content is specific enough.
- Deduplicate placements (same triple).
- For multi-exam concepts, add placements per exam/subject as appropriate (one revision summary can serve multiple placements).
- Keep placements consistent with note generation expectations.

## 4) Study Notes Contract (Production-Format, Exam-Ready)
Generate **one canonical note per production placement** (synthesized from concepts, not 1:1 concept dumps).

### Required structure (must match `topic_notes` schema / `scripts/validate_notes.py`)
- `id`, `exam`, `subject`, `topic_slug`, `subtopic_slug`, `title`
- `read_time_minutes` (1-6, computed from word count per validator)
- `key_takeaway` (RichText object `{text, inline:[]}`)
- `sections[]` (2-5 sections), each `{section_number, heading, content: RichText, callout?}`. Headings have **no** manual numeric prefixes. Callout kinds only `key_concept|examiner_tip|warning|law|definition`.
- `worked_examples[]`, `formulas[]`, `active_recall_checks[]`, `examiner_traps[]`, `linked_question_ids[]`
- `sources[]` with `title`, absolute `http(s)` `url`, and `locator` (non-empty). No search-result URLs.

### Quality requirements (exam-polish)
- **Synthesize**: Aggregate all relevant concepts for that placement into one coherent note; deduplicate; order logically.
- **Grounded**: Only use content from sourced concepts/sources. Do not invent facts, examples, figures, answers, or traps.
- **Clear and direct**: Use natural exam language. Avoid AI-ish/meta phrasing (e.g. "supported by the sourced material", "it is important to note", "delve", "comprehensive", "crucial" overuse). Avoid em/en dashes.
- **Exam-oriented**: Include practical, grounded recall checks and examiner traps where derivable from sources; include worked examples only if present/safely derivable from sourced material.
- **Concise but complete**: Cover the subtopic/topic objectives as scoped by production; prefer precision over padding.
- **Provenance**: Every note must have valid sources traceable to concepts/attribution.

### Generation
Use a synthesis approach (aggregate by placement, clean headings/content, derive grounded checks/traps, validate). Output to `data/generated-notes/prod-topic-notes-<subject-or-scope>.json`.

Validation: `python3 scripts/validate_notes.py <notes.json>` must pass.

## 5) Definition of Done (Per Subject/Task)
A subject/task is **done** only when all of the following are true:

### Mapping & Coverage
- [ ] Production catalog snapshot fetched/refreshed for target `(exam, subject)` pairs
- [ ] Every production topic and subtopic mapped in `audit-*.json` or marked `no_source` with explicit rationale
- [ ] Coverage audit doc updated (sources/licence tables, matrices, gaps)
- [ ] No unexplained unmapped required items

### Concepts & Placements
- [ ] All required concepts created/updated in `data/concepts/` following schema v4
- [ ] Each concept has complete `source_attribution` (url/locator/licence) and valid `revision_summary`/`deep_context`
- [ ] `placements[]` match production slugs exactly; validated against catalog
- [ ] `python3 scripts/validate_concepts.py` passes (0 errors)

### Notes (Replacement-Ready)
- [ ] Canonical notes generated: **one per production placement** for in-scope subjects
- [ ] Notes synthesized from concepts (no 1:1 concept-dump), exam-polished, no em/en dashes, no generic AI/meta boilerplate
- [ ] Notes grounded in sources; provenance present in `sources[]`
- [ ] `python3 scripts/validate_notes.py <notes.json>` passes
- [ ] Note content reviewed for obvious quality issues (headings clean, recall/traps reasonable and grounded)

### Ingestion Readiness
- [ ] `data/concepts-ingestion-manifest.json` updated
- [ ] Artifacts are in gitignored `data/` as appropriate (concepts/notes/manifests/audits staging); tracked docs updated only if needed for accuracy
- [ ] If ready to import: notes validated and concept objects prepared per manifest (upload to static storage/ingest via `cargo run -- import-notes ...` as applicable)

### Final Check
- [ ] Changes are consistent with surrounding patterns and this contract
- [ ] Gaps/limitations documented (thin topics, review-pending licences, missing sources/media)

**Rule:** Do not mark done if validators fail, placements are guessed/mismatched, content is invented, or notes are un-synthesized/raw dumps. If something cannot be sourced, mark `no_source`/document the gap rather than fabricating content.