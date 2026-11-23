# Proposal: syllabus revision metadata for study planning

**Status:** Consumer-driven proposal; needs API maintainer review
**Raised from:** UtmeLab study-planning and offline-readiness design
**Date:** 2026-11-20

## Summary

Expose authoritative revision/provenance metadata for the syllabus snapshot
returned by the subject syllabus endpoint. A consumer preparing a learner for
a target exam cycle needs to know which syllabus snapshot it has stored, when
that snapshot was observed, and whether the source actually defines an
effective year or edition.

This proposal does **not** assume that JAMB publishes a different syllabus
every year. Target exam year, syllabus revision, and past-question year are
separate concepts and must not be collapsed into one `year` field.

## Current observed contract

The current route is:

```text
GET /api/v1/subjects/{exam}/{slug}/syllabus
```

It serves an ordered topic/subtopic tree with objectives, country scope, and
question counts, plus a summary. `build_syllabus` resolves a configured
syllabus owner where needed, reads the current catalog tree, aggregates live
question-bank counts, and attaches note indicators. The wire `Syllabus` shape
contains `exam`, `subject`, `topics`, and `summary`; it has no syllabus
revision/source identifier or effective period.

The question routes separately allow filtering questions by `year`; this is
past-question metadata and does not identify the revision of the syllabus.
Responses also carry a global `x-bank-version`, but it is not an explicit
syllabus revision contract and may change for unrelated bank content.

The schema documentation describes `syllabus_version` on the exam-to-textbook
mapping, but this value is not surfaced as the revision identity for the
syllabus tree response.

JAMB's official site links to the Integrated Brochure and Syllabus System
([IBASS entry point](https://jamb.gov.ng/ibass)). This supports treating the
official syllabus system as a source to cite and audit. It does not establish
from the public page alone that every exam year has a separate syllabus
edition. The API should report only source-backed version/effective-period
facts.

## Consumer problem

UtmeLab plans have an exam target cycle/year and prepare syllabus and related
teaching content locally for offline use. To make that plan reproducible and
refresh it safely, the client needs to distinguish:

1. **Exam cycle/year:** when the learner intends to sit the exam.
2. **Syllabus revision:** which official curriculum tree the plan uses.
3. **Question year:** the year a past-paper question is associated with.
4. **Bank/content version:** the API dataset state used for cache validation.

Today the client can retain a whole syllabus payload and observe the global
bank version, but it cannot cite a syllabus-specific revision or know if the
source has supplied an effective period. Treating the target exam year as the
syllabus version would be an unsupported inference.

## Proposed contract direction

Add backward-compatible optional metadata to the syllabus response, or provide
an equivalent stable resource/metadata endpoint:

```json
{
  "exam": "JAMB",
  "subject": {},
  "topics": [],
  "summary": {},
  "revision": {
    "id": "source-defined-stable-revision-id",
    "label": "source-defined-label",
    "source": "official-source-identifier",
    "source_url": "https://...",
    "source_locator": "page, document, or section locator",
    "published_at": null,
    "effective_from": null,
    "effective_to": null,
    "observed_at": "2026-11-20T...",
    "content_hash": "optional-stable-payload-hash"
  }
}
```

This is illustrative, not a demand for these exact field names. Requirements:

- Revision identity is stable for the same authoritative syllabus snapshot.
- Source, source locator, and observation time are explicit.
- Effective years/dates are nullable and emitted only when supported by the
  source or an explicitly documented API editorial decision.
- If the source has one current syllabus without a year-specific edition, the
  API can identify the current revision without manufacturing an annual range.
- Content changes produce a detectable revision/hash change.
- Existing response fields and clients remain compatible; absent metadata is
  represented as unknown, not as empty/zero or an inferred year.
- Question `year` and the response-wide bank header retain their existing
  separate meanings.

If `exam_syllabus_map.syllabus_version` is already authoritative, document how
it relates to the syllabus tree revision and expose a consistent identifier.
If it is only a mapping author's annotation, do not treat it as the full
syllabus revision without further provenance.

## Suggested implementation investigation

Before changing the schema:

1. Confirm what source material and update process currently populate `topics`
   and `subtopics`.
2. Determine whether JAMB/other boards identify syllabus editions or effective
   years, and whether the content repository keeps source snapshots.
3. Establish whether `syllabus_version` in textbook mapping records refers to
   an official syllabus edition, an internal mapping revision, or both.
4. Decide whether revision metadata belongs in a dedicated revision table,
   current catalog metadata, or the served syllabus envelope.
5. Keep versioning per exam/subject/syllabus owner; do not reuse a single
   global bank version as the only curriculum identity.
6. Specify how country-scoped syllabus responses relate to the underlying
   revision identity.

## Acceptance criteria

- A client can identify and persist the syllabus snapshot it received.
- A subsequent request can tell whether that syllabus revision changed,
  independently of question years and unrelated bank changes.
- When source dates/edition are unavailable, the response says so by omission
  or explicit nullable metadata; it never invents an exam-year label.
- Shared-syllabus ownership (for example one exam subject mapped to another
  syllabus owner) still identifies the requested offering and the underlying
  syllabus revision unambiguously.
- Topic ordering, objectives, country scope, and live question counts retain
  current semantics.
- API tests cover current/unknown revision metadata, changed revision,
  backward-compatible serialization, and owner mapping.
- OpenAPI and content-access documentation explain the distinction between
  syllabus revision, exam cycle, question year, and bank version.

## Non-goals

- This proposal does not define learner study plans or progress APIs.
- It does not require the API to create a new syllabus per calendar year.
- It does not change question sampling, counts, or content coverage.
- It does not ask the API to proxy/store app-specific offline caches.
- It does not ask for a new endpoint unless an envelope field cannot provide
  the needed revision contract.
