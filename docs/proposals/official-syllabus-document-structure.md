# Proposal: preserve official syllabus document structure

**Status:** Consumer-driven proposal; needs API maintainer review
**Raised from:** UtmeLab syllabus browsing
**Date:** 2026-11-21

## Summary

The syllabus endpoint should expose a source-backed representation of the
official syllabus document, including its overview, section hierarchy, and
distinct content and objective statements. Consumers should be able to render
that structure without writing curriculum copy or inferring missing material.

The API remains the content source for UtmeLab. This proposal asks the API to
represent and cite board-published material. It does not ask the app to create,
paraphrase, or fill gaps in syllabus content.

## Evidence and current contract

JAMB's [IBASS E-syllabus](https://ibass.jamb.gov.ng/e-syllabus) provides
subject-specific official syllabus documents. The observed Use of English
document has general objectives, named sections, and a detailed table with
topics, contents, notes, and candidate objectives. This is one concrete
example of a board's document structure, not a claim that every board uses
the same headings or table.

The current route is:

```text
GET /api/v1/subjects/{exam}/{slug}/syllabus
```

The response in `src/core/models/wire.rs` contains an exam, subject, ordered
topics, and a summary. Topics and subtopics expose names, order, objectives,
country scope, and live question counts. Topics also expose note availability.
The stored topic model in `src/core/models/domain.rs` has no syllabus-level
overview, named section, or distinct syllabus-content and source-note fields.
The current shape therefore cannot represent all of the observed document
without flattening or conflating its parts.

These existing fields describe separate things and should keep their current
meaning:

- `objectives` are examinable statements, not topic descriptions.
- `question_count` and the summary counts describe live practice-bank
  coverage. They are not counts of syllabus requirements or questions set by
  the board.
- `has_note` and `note_id` describe API study-note availability. They are not
  the official syllabus document's notes column.
- `subject.objective_paper_questions` describes a paper's stated question
  count. It is not part of the syllabus tree.
- A topic's `weight` is not a substitute for source ordering or a section.

The existing proposal
[`syllabus-revision-metadata-for-planning.md`](./syllabus-revision-metadata-for-planning.md)
covers revision identity, source citation, and effective dates. This proposal
depends on that work for provenance and should be coordinated with it rather
than define a second revision system.

## Consumer problem

A syllabus browser needs to show the board's own learning outline in its
original hierarchy. With the current response, a consumer can list topics and
objectives, but cannot reliably show:

- document-level aims or general objectives;
- named sections that group topics;
- syllabus content or scope statements separately from candidate objectives;
- source-document notes separately from the API's study notes; or
- a citation that identifies where a displayed statement came from.

When these distinctions are absent, clients may be tempted to turn topic
names or objectives into descriptions, or to present practice availability as
part of the official curriculum. The API should make those interpretations
unnecessary.

## Proposed contract direction

Extend the current syllabus response additively. Keep the existing `topics`,
`summary`, and enrichment fields for current clients. Add an optional
source-backed document layer, with section headings that reference existing
topic slugs rather than copying topic objects:

```json
{
  "document": {
    "source": {
      "publisher": "JAMB",
      "title": "Official source document title",
      "url": "https://official-source.example/document",
      "locator": null
    },
    "general_objectives": null,
    "sections": [
      {
        "slug": "section-a",
        "name": "Source heading",
        "order": 1,
        "topic_slugs": ["topic-one"]
      }
    ]
  },
  "topics": [
    {
      "slug": "topic-one",
      "syllabus_content": null,
      "source_notes": null,
      "objectives": []
    }
  ]
}
```

All names and text in the example are illustrative placeholders, not proposed
syllabus content. The exact wire names can change during API design. The
contract should meet these requirements:

- Preserve wording, order, and hierarchy from the cited official source.
  Do not derive descriptions or content by rewriting objectives.
- Keep syllabus content, source-document notes, and candidate objectives in
  separate fields. Where the source groups statements differently, retain the
  source's labels or structure instead of forcing them into these example
  fields.
- Allow section headings to group existing topic records without duplicating
  their question counts, note indicators, or objectives.
- Use optional values or an explicit completeness state to distinguish
  unknown or uncollected source material from a source that was checked and
  has no such material. An empty list alone should not imply both.
- Record a source URL and a useful document locator, such as a page, heading,
  or table location. Coordinate stable revision identifiers and dates with
  the existing revision-metadata proposal.
- Keep each statement attributable to its source. If a syllabus combines
  sources, allow an item-level locator where a single document-level citation
  is not enough.
- Retain the requested exam and subject offering in the response when that
  offering maps to a shared syllabus owner. Make the underlying syllabus
  owner and source clear without changing the existing mapping behavior.
- Keep country-specific inclusion rules explicit. Do not imply that one
  country's syllabus applies to all countries when the source or catalog says
  otherwise.
- Keep API-generated practice coverage and study-note availability as
  separately labeled enrichments. A zero live question count means no linked
  practice items are available in the current bank, not that the syllabus
  contains no material.
- Leave exam format and paper rules in their existing exam-scheme contract
  unless a cited syllabus document itself contains that information. Do not
  infer paper structure from syllabus headings.

The API may use a normalized internal model or source documents plus a
projection. The public response should avoid conflicting duplicate copies of
the same topic statements.

## Source and editorial policy

The API should treat the board-published document as the authority for
syllabus wording. Data entry or import may normalize layout for machine
reading, but it should not silently rewrite, omit, or complete the board's
statements. Preserve source order and document labels.

When no official source is available or a field has not been transcribed, the
API should say that the information is unavailable. It should not fill the
gap with app-authored copy, generated summaries, assumptions from another
exam, or practice-bank metadata. Any editorial material the API chooses to
offer in the future should be explicitly labeled as editorial and kept
separate from official syllabus content.

Before using a source document, API maintainers should confirm the applicable
rights and permitted distribution. A citation does not itself grant
permission to reproduce the document.

## Suggested investigation

1. Inventory source documents and current source records for JAMB, WAEC, and
   NECO. Record what is actually present before declaring any board data
   incomplete.
2. Compare the stored tree and response against each source document. Identify
   where section headings, general objectives, content statements, source
   notes, and country scope are preserved, missing, or transformed.
3. Decide whether the current topic tree can represent the source faithfully
   with additive fields or whether the document needs a normalized
   source-structure model.
4. Define provenance and revision handling with
   `syllabus-revision-metadata-for-planning.md`. Avoid a second source or
   version identifier with different semantics.
5. Confirm the storage/import and review process can preserve exact wording,
   ordering, source locators, and unknown-versus-empty states.
6. Update the public and authenticated syllabus contracts consistently, then
   document the distinction between curriculum statements and API practice
   availability.

## Acceptance criteria

- For each supported syllabus, a consumer can render the source-backed
  hierarchy and statements that the API has actually captured.
- A test fixture based on an official document verifies its section order,
  topic membership, and distinction between content statements and
  objectives.
- Source-document notes cannot be mistaken for `TopicNote` study content or
  `has_note` availability.
- Missing, untranscribed, and source-confirmed-empty data have distinct,
  documented representations.
- Existing clients can continue reading the current topic tree and
  enrichment fields. Existing question counts, summary counts, country
  filtering, and shared-syllabus ownership retain their semantics.
- OpenAPI and endpoint documentation describe the new fields and state that
  the API does not infer or author missing official curriculum.
- No proposal example or migration creates syllabus statements that are not
  present in a cited source.

## Non-goals

- This proposal does not add syllabus content in the app or author official
  curriculum.
- It does not ask the API to guarantee that every board publishes the same
  kind of overview, sections, or tables.
- It does not change question tagging, question counts, topic weights, exam
  paper sizes, or study-note content.
- It does not prescribe a full document-rendering format or require a new
  endpoint.
- It does not assume that JAMB publishes a new syllabus each year.
