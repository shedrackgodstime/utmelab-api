# Long-Term Plan: From Revision Notes to Serious Edtech Platform

Status: Plan for review
Date: 2026-11-09

## Purpose

This plan describes how the current study-notes system can grow toward a serious
educational technology platform with AI tutoring and learning features, without
breaking the existing mobile revision experience. The data structure is defined
in [`docs/CONCEPT-DOCUMENT-SCHEMA.md`](https://github.com/shedrackgodstime/utmelab-bank/blob/main/docs/CONCEPT-DOCUMENT-SCHEMA.md).

## Current state

The platform serves high-yield study notes through a compact API. Notes live in
the `topic_notes` table, are keyed by exam, subject, topic slug and optional
subtopic slug, and are limited to under 16 KiB per note in serialized JSON.

Production holds 26 notes across four exam and subject pairs: JAMB mathematics 5,
JAMB physics 2, JAMB use-of-english 12, and WAEC english-language 7. The local
draft folders hold 24 notes across three pairs; the 2 physics notes are
hardcoded seeds. Every shipped note carries verified sources with locators,
structured sections, worked examples, formulas, active recall checks, and
examiner traps.

The catalogue includes a question bank, theory questions with marking rubrics,
durable production exports, and a preflight validator for notes.

## Decision: Option A (build-time ingestion)

The authored content is one JSON document per shared concept, held on static
object storage outside git and outside the operational database. The database
holds only the revision summary plus a pointer to that document. The public
notes API serves the revision summary from SQLite with zero external latency
and never fetches the static document at request time. AI retrieval and
deep-reading views fetch the full document directly from static storage.

## Design principle: two tiers

The long-term design separates content by use and by contract:

**Tier 2: Revision cards (current public API).**
Compact notes for rapid study on mobile. Contract: under 16 KiB, 3 to 5 minute
read, 2 to 4 sections, worked examples, recall checks, and examiner traps.
Served offline from the local replica.

**Tier 1: Canonical knowledge documents (future retrieval layer).**
Full textbook-grade depth per shared concept: definitions, derivations, figures,
examples, and practice. Stored as static JSON files, not in git and not counted
against the 16 KiB public note ceiling. Used by future AI retrieval, deeper
explanation views, and question generation.

Tier 2 is synthesized from Tier 1 at ingest time. Tier 1 is not served through
the public notes endpoint.

## Phase 1: Canonical document and ingestion skeleton

Goal: prove that one authored document can serve multiple exams without changing
the public API.

- Define the authored document shape in [`docs/CONCEPT-DOCUMENT-SCHEMA.md`](https://github.com/shedrackgodstime/utmelab-bank/blob/main/docs/CONCEPT-DOCUMENT-SCHEMA.md).
- Add two nullable pointer columns to `topic_notes`: `concept_slug` and
  `concept_url`. No new join table is introduced.
- Author one pilot document: right-triangle trigonometry, from OpenStax
  Algebra and Trigonometry Section 7.2, including the licensed figure and
  attribution in `deep_context`, and a compact `revision_summary`.
- Ingest the pilot through the existing import path, mapping the same revision
  summary to both the JAMB mathematics and WAEC general mathematics placements.
- Update the study-notes specification with the pointer columns and the
  two-tier model.

Exit criteria: pilot document passes validation; both placements resolve to
rows with identical revision content; existing 26 notes unchanged;
`cargo test` passes.

## Phase 2: Coverage by syllabus order

Goal: grow coverage in syllabus order, not by current question volume.

Priority order:

1. JAMB mathematics topics 1 and 2 (Number Bases; Fractions, Decimals,
   Approximations and Percentages).
2. WAEC english-language topics waec-lexis, waec-structure and waec-stress.
3. JAMB physics topics Measurements and Units, and Scalars and Vectors.

Each new concept is authored once as a static document, then ingested into one
or more placement rows. Each ingested row must pass the content repository's
`book/validate_notes.py`, carry verified sources with locators, and keep the
16 KiB ceiling. Figures are
added only where the meaning is spatial, graphical or layout based, and only
from licensed sources with attribution.

Target: on the order of 60 to 80 verified notes across the four current pairs
before AI work begins.

## Phase 3: Canonical ingestion for retrieval

Goal: build the retrieval-ready knowledge base for AI features.

- Ingest openly licensed textbook sections into static concept documents for
  mathematics and science subjects first.
- Record licence per book in the document metadata. Verify commercial-use terms
  per title before any paid feature uses that content.
- Store figures with source attribution and alt text; do not hotlink external
  images.
- Add a retrieval index over `deep_context` bodies so future services can fetch
  grounded context by concept slug.
- No new public endpoint in this phase; retrieval remains internal.

## Phase 4: First AI feature

Goal: ship one grounded AI feature and measure it.

- Grounded Socratic hints: on a wrong answer, retrieve the canonical context
  from static storage and generate progressive hints (concept reminder, formula
  setup, intermediate step) with citations to the concept and source locator.
- Measure hint accuracy, citation correctness, and cost per query.

Gate: expand to further features only after this feature meets accuracy and
cost thresholds.

## Phase 5: Later learning features

Listed here for sequencing only; none is committed in Phase 4:

- Theory-answer diagnostic feedback against examiner rubrics and canonical
  concepts.
- Adaptive question generation that preserves mathematical structure while
  varying numbers and context.
- Learner progress dashboards that join notes, questions, and concept
  coverage.
- Read-full-chapter views that render `deep_context` on demand.

## Data governance

- The live database is the source of truth for revision cards.
- Static concept documents are the source of truth for deep content and are
  held outside the repository.
- The repository holds code and configuration, not product data.
- The content repository keeps `data/notes/`, `data/theory/`,
  `data/notes-snapshots/` and `data/notes-replacements/` local-only and
  gitignored.
- Durable exports are produced with the content repository's
  `book/export_notes.py` after each bulk import and retained locally with
  per-note hashes.
- The source manifest ([`docs/STUDY-NOTES-SOURCE-MANIFEST.md`](https://github.com/shedrackgodstime/utmelab-bank/blob/main/docs/STUDY-NOTES-SOURCE-MANIFEST.md)) records which
  sources support which claims and which claims were withdrawn.
- Existing production notes can be replaced wholesale as their canonical
  documents are authored; no dual-version maintenance is required.

## Non-goals

- Whole-textbook chapters are not copied into public notes.
- Textbook markdown is not stored in git or in the operational replica.
- NECO notes are not started until the paywalled syllabus and reports are
  resolved.
- The figure pipeline does not expand until the first sourced figure passes
  visual review.
