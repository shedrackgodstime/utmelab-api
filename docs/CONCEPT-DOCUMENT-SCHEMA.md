# Concept Document Schema (Option A)

Status: Data structure specification, block model
Date: 2026-11-09

## Decision

Option A is adopted: build-time ingestion.

- The authored document lives as one JSON file on static object storage (for example Cloudflare R2 or Cloudflare Pages), outside git and outside the operational Turso replica. Local staging is `data/concepts/{concept_id}.json` with `data/concepts/images/` for figures; that directory is gitignored.
- The operational database holds only the revision summary needed by the public notes API, plus a pointer to the authored document.
- The public notes API does not fetch the CDN document at request time. It serves the ingested row from SQLite with zero external latency.
- AI and deep-reading services read `deep_context` directly from static storage. They do not pass through the notes API.
- One authored document per shared concept. Revision cards, full-chapter views, and AI retrieval are different projections of that document. No second schema and no adaptor: every block speaks the project types.

## Authored document (static JSON)

Fields:

- `concept_id`: string, canonical slug such as `math_right_triangle_trigonometry`. Stable identifier; never reused for a different concept.
- `schema_version`: integer. Current version: 4.
- `updated_at`: string, ISO 8601 date of the last content edit.
- `title`: string.
- `subject_area`: string, broad area such as mathematics, physics, or english_language.
- `source_attribution`: object.
  - `publisher`: string, for example OpenStax.
  - `book`: string.
  - `section`: string.
  - `url`: string.
  - `licence`: string, exact licence identifier for that book, preserved per title.
  - `locator`: string, section, figure, table, or page range.
- `revision_summary`: object. This is the compact revision card. It maps one to one onto the existing `TopicNote` content fields.
  - `read_time_minutes`: integer.
  - `key_takeaway`: RichText (text plus inline offsets).
  - `sections`: array of NoteSection (section number, heading, content RichText, optional callout).
  - `worked_examples`: array of WorkedExample.
  - `formulas`: array of NoteFormula.
  - `active_recall_checks`: array of ActiveRecallCheck.
  - `examiner_traps`: array of ExaminerTrap.
  - `sources`: array of NoteSource (title, url, optional locator).
- `deep_context`: object. Textbook-grade depth for AI retrieval and full-chapter views. Stored as ordered blocks, not a pre-baked string, so any consumer can render it to `full_markdown` at process time.
  - `blocks`: ordered array of Block. This is the entire deep content in reading order. Every block has `id`, `type`, and `level` (`core` or `enrichment`). `core` blocks are the JAMB/WAEC syllabus scope; `enrichment` blocks are textbook depth (proofs, cross-cultural notes, omitted-figure context) shown only on demand.
- `placements`: array of objects. Each entry states where the revision summary applies.
  - `exam`: string.
  - `subject`: string.
  - `topic_slug`: string.
  - `subtopic_slug`: string or null.
  - `exam_lenses`: optional array of objects. Each entry may carry exam-specific examiner traps, worked examples, or recall checks that supplement the shared revision summary.

## Block types

Every block is an object with `id` and `type`. Content is always `RichText` (`text` plus `inline` offsets) or `latex` (LaTeX string). No HTML, no Markdown stored.

| Type | Extra fields | Used for |
|---|---|---|
| `heading` | `level`, `text: RichText` | Chapter, section, subsection titles |
| `paragraph` | `content: RichText` | Narrative explanation, introductions, context |
| `definition` | `term: RichText`, `definition: RichText`, `latex?` | Key terms, glossary entries, vocabulary (English lexis, Psychology terms, Biology terms share this shape) |
| `theorem` | `statement: RichText`, `latex?`, `proof_steps: Block[]` | Calculus theorems (Constant Rule, Power Rule, Sum Rule) with their proofs |
| `proof` | `steps: Block[]` | Proof sub-blocks; may also stand alone under a theorem |
| `procedure` | `title: RichText`, `steps: Block[]` | OpenStax How To blocks, stoichiometry factor derivations, cloze reading steps, tall-object measurement steps |
| `example` | `kind: worked|try_it`, `problem: RichText`, `strategy?`, `solution?`, `discussion?`, `answer?`, `answer_provenance?`, `figure_ref?` | Worked examples and Try It / Checkpoint items. Try-it answers on the student page are not printed; mark any supplied answer as derived by the project |
| `exercise` | `id`, `prompt: RichText`, `category`, `figure_ref?`, `asset_url?` | Section exercises (Verbal, Algebraic, Graphical, Technology, Extensions, Real-World). Unnumbered exercise images live here, not in `figures[]` |
| `figure` | `asset_url`, `anchor`, `caption: RichText`, `alt`, `referenced_by[]`, `licence`, `credit?`, `panels[]?` | Numbered figures (Trig 1-15, Physics 3.34-3.38). Multi-panel figures store panels (a)-(d) as sub-assets |
| `table` | `title?`, `rows[][]` | Cofunction Table 1, comparison tables (reduction/oxidation, Table 6.1), recipe tables |
| `passage` | `text: RichText`, `source_note?` | English comprehension passages, Literature excerpts, Government preambles |
| `cloze` | `text: RichText` with blank anchors, `options[][]`, `answers[]` | Cloze tests as structured blanks inside a passage |
| `quote` | `text: RichText`, `attribution?` | Poetry lines, play dialogue, quotations |
| `media` | `title`, `url`, `media_type?` | Media links and interactive embeds (OpenStax short-code links) |
| `formula` | `latex`, `variables[]`, `conditions[]`, `equation_no?` | Formula blocks with variables and conditions; physics equation numbers preserved |
| `summary` | `points: RichText[]` | Section Key Concepts bullets, chapter summaries |
| `glossary_entry` | `term: RichText`, `definition: RichText` | Key Terms lists; may be rendered as `definition` blocks when order matters |

Rules:

- `revision_summary` must serialize to under 16 KiB when mapped to a `TopicNote`.
- Heading numbers come only from `section_number` in revision sections and from `level` plus order in deep blocks; headings carry no manual numeric prefix.
- Callout kinds are limited to key_concept, examiner_tip, warning, law, definition.
- Inline offsets are Unicode scalar offsets into the owning text.
- The full document may exceed 16 KiB; only `revision_summary` carries the public ceiling.
- A deterministic renderer converts `deep_context.blocks` in order to `full_markdown` at request time. Stored data stays structured so `revision_summary` can change without rewriting `deep_context`.

## Operational database pointer

`topic_notes` gains two nullable columns. No new join table is introduced.

- `concept_slug`: TEXT NULL, the authored document key. Null means a locally authored note with no canonical document.
- `concept_url`: TEXT NULL, the resolved CDN URL for the document. Stored at ingest time. The API returns it as a string so clients can fetch `deep_context` on demand without involving the notes handler.

Existing columns and behaviour are unchanged. `topic_notes` still holds the entire revision summary. The content hash covers the revision fields and sources. Deep-only edits do not change revision hashes.

## Ingestion (build time)

1. Fetch `concepts/{concept_id}.json` from static storage.
2. Validate `revision_summary` against the note preflight rules: size ceiling, placement, inline offsets, callout kinds, heading prefixes, read time from word count, and source coverage. The same validator also checks that every `blocks[]` entry has an id, a known type, and RichText offsets inside its text.
3. Map each entry in `placements` to a `TopicNote` row: exam, subject, topic slug, subtopic slug, title, and the shared `revision_summary` fields, plus any exam-specific additions from `exam_lenses`.
4. Import through the existing `import-notes` path, which revalidates size and placement and recomputes the content hash.

If a concept serves two exams, ingestion writes one row per placement from the same revision summary. The rows share content but keep separate placement and hash records.

## Serving

- Revision requests: the handler reads the row from SQLite, resolves media URLs, enforces the 16 KiB ceiling, and returns the note. It performs no fetch to static storage.
- Deep requests: clients or the AI retrieval service fetch the CDN URL from `concept_url` directly and read `deep_context.blocks`. The notes API is not in that path. A client that wants more after the revision card renders the remaining blocks with the same RichText renderer it already uses for notes.
- Figures referenced by inline images in `revision_summary` and by `figure` blocks in `deep_context` resolve against the same media base URL.

## Existing notes

The 26 live notes are revision summaries without canonical documents. They remain servable until each is migrated into an authored document or replaced. Migration is a pure content move: a note's sections, examples, formulas, checks, traps, and sources become the `revision_summary` of its concept document, and extended material goes into `deep_context.blocks`.

## Reversibility

If the project later chooses to serve deep content from the application server, only the ingestion step changes: the server can read `deep_context` from static storage at request time and slice it per view. The authored document shape and the stored revision rows remain unchanged, so clients and stored data do not need to move.
