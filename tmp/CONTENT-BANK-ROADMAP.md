# Content bank roadmap

This file records the phased plan for `utmelab-bank`. Read it before starting
new content-bank work. Work on one phase at a time.

## Objective

Fill and review exam content for the public UTME Lab API. Keep the bank stable,
repeatable, and safe to rerun. The bank prepares content and does not write the
serving API content tables.

The current product focus is content coverage and content quality. Learner
progress, billing, the dashboard, and the full documentation site are outside
this phase of the project.

## Operating rules

1. Inspect the current code, database state, workflow history, and existing
   writeups before changing a pipeline.
2. Work on one bounded phase or one small fix.
3. Test locally with fixtures or mocks before using a real provider.
4. Test one real row before starting a batch.
5. Keep provider, model, latency, status, and error category on every failure.
6. Do not invent subjects, syllabus entries, answers, explanations, or source
   facts.
7. Use official exam naming and the production catalogue as the authority.
8. Keep rejected, malformed, duplicate, and provider-failed rows visible in the
   bank.
9. Do not run a large batch while a provider or schema change is unverified.
10. After each phase, record the result, commit, push, and confirm CI.

## Current state

Completed:

- MySchool scraping, deduplication, malformed-row handling, and production
  duplicate checks are active.
- WAEC subject naming and syllabus inputs have been checked against the
  production catalogue.
- The bank uses its own Turso database and reads the production catalogue with
  a read-only credential.
- The workflow uses pinned OpenCode v2.0.28 and checks the installed version.
- OpenCode errors expose provider, category, status, and retryability.
- OpenCode quota and multiline error events are classified correctly.
- OCR.space is the only retained OCR service.
- OCR results are stored per image with extracted text and word coordinates.
- OCR text is passed to the vision provider as supporting evidence.
- OCR preprocessing validates images, handles transparency, corrects
  orientation, and enlarges small captures.
- OCR and deterministic media-check evidence survives staging database reloads.
- Tag evidence accepts only normalized text from the row or accepted OCR
  evidence, and catalog ids still have to pass the production snapshot.
- READY now refuses any media check that is not `ok`, including review-needed
  OCR evidence.
- Real-image OCR testing found malformed `.png` files and diagram-only images.
- The latest repository quality gate passed after the OCR preprocessing change.

## Phases

### Phase 1: Media foundation

Status: active and mostly complete.

Keep the original image unchanged for vision work. Create a separate OCR copy.
Validate image bytes before sending them to a provider. Store OCR output and
OCR failures in evidence.

Exit check:

- OCR tests cover success, empty text, malformed bytes, provider errors, and
  word coordinates.
- The image branch can continue when OCR fails.
- A malformed image cannot reach a model provider unnoticed.

Next action: freeze the current OCR implementation and do not add another OCR
provider yet.

### Phase 2: Golden content benchmark

Create a small permanent set of real bank rows. Keep the set in a controlled
test fixture or a private benchmark location. It should cover:

- clear text inside an image;
- small labels;
- a table;
- a graph or circuit;
- a biology diagram;
- a chemistry structure;
- an equation or calculation;
- an image with no text;
- a malformed image;
- a low-quality capture.

Record expected observations, not invented answers. Measure OCR extraction,
image description, tagging, explanation, latency, and provider failures.

Exit check: every provider or prompt change can be compared against the same
rows.

Current checkpoint: the manifest and local validation test are in
`utmelab-bank/tests/fixtures/benchmark/`. The 14 image observations are now
manually labelled. The complete cases still need source-question, catalogue,
answer, and explanation labels before they become verified gold cases.
The first OCR.space baseline scored 11 of 14 media cases, with failures kept
visible for the electrical, air-label, and force-vector images.

### Phase 3: Deterministic media checks

Add checks that do not need a model:

- image bytes and MIME type are valid;
- dimensions are usable;
- the stored asset hash matches the bytes;
- OCR text is empty, weak, or usable;
- a text-heavy image with empty OCR is flagged;
- a diagram with empty OCR is allowed to continue;
- OCR and vision evidence can be marked as agreeing or conflicting.

Exit check: the media branch classifies malformed, weak, text-bearing, and
diagram-only images without guessing what the image means.

### Phase 4: Image descriptions

Improve the image description contract and prompts.

- Separate visible facts from inferences.
- Include labels, values, units, arrows, axes, and relationships when visible.
- Include OCR text as evidence, not as unquestioned truth.
- Require uncertainty when part of an image is unreadable.
- Compare independent witnesses by facts, labels, and values instead of only
  comparing the final description string.

Exit check: the golden benchmark reports witness agreement and keeps disputed
figures out of the ready state.

Deferred options: Mathpix for equations and chemistry diagrams, and PaddleOCR
as a self-hosted OCR fallback. Do not add either before the benchmark shows a
need.

### Phase 5: Tagging

Make tagging more controlled before increasing its batch size.

- Retrieve a small catalogue candidate set for the question.
- Require an exact topic and subtopic ID from that set.
- Require evidence copied from the question, passage, or accepted OCR text.
- Reject dangling or cross-scope IDs.
- Add a confidence threshold and an abstain path.
- Send low-confidence and conflicting tags to review.

Exit check: every accepted tag is supported by evidence from the row and the
production catalogue.

### Phase 6: Explanations

Improve explanations after tagging is stable.

- Confirm that the explanation agrees with the canonical answer.
- Explain the correct option and every distractor.
- Preserve the question's terminology and units.
- Require calculation steps for numerical questions.
- Use OCR and image evidence when the question depends on a figure.
- Mark unsupported or uncertain claims for review.

Exit check: the explanation validator catches answer changes, missing
distractor reasoning, unit errors, and unsupported figure claims.

### Phase 7: Provider layer

Add providers only when the benchmark identifies a gap.

- Keep the mock provider for deterministic tests.
- Keep OpenCode as an optional provider, not as a guaranteed service.
- Add the direct NVIDIA provider through its OpenAI-compatible API when the
  NVIDIA key is ready.
- Keep provider errors separate from content errors and bank errors.
- Add quota, authentication, timeout, transport, protocol, and output-schema
  categories for every provider.
- Test provider switching on the same row without changing row data.

Exit check: a provider can fail without hiding the row or misleading the
operator about the source of the failure.

### Phase 8: Review and release readiness

Build the final content quality loop.

- Sample rows from every exam, year, subject, source, and provider.
- Review disagreement and low-confidence queues first.
- Track ready, rejected, duplicate, malformed, and provider-failed counts.
- Recheck content hashes before production handoff.
- Keep the bank output separate from production writes.

Exit check: a ready row has valid source data, valid media, catalogue placement,
answer verification, explanation evidence, and a complete audit trail.

## Deferred work

Do not start these during the current content phase:

- learner progress;
- billing and usage dashboards;
- the public dashboard;
- broad provider expansion without benchmark evidence;
- automatic production writes;
- a large batch against an unverified provider;
- a second OCR service before OCR.space has been measured on the benchmark;
- a write-capable AI agent in GitHub Actions.

## Continuation instruction

When starting a fresh session, read this file, `utmelab-bank/README.md`, the
latest `tmp/AUDIT-STATUS.md`, and the current workflow files. Check `git status`
and the latest quality run. Continue from the first phase whose exit check is
not complete. Do not restart completed work.
