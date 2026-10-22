# Content Factory Findings

**Status:** evidence file, not a roadmap. `ROADMAP.md` remains the roadmap.

**Scope:** `tools/`, `utmelab-bank/`, `utmelab-pipeline/`, `utmelab-api-old/docs/`, and `docs/NOTES.temp.md`.

**Date:** 20 October 2026.

**Tree state:** the bank already had uncommitted changes before this file was written. This file only adds `utmelab-bank/FINDINGS.md` and does not modify code.

## 1. The objective

The factory takes a source scope, such as one exam, subject and year, and produces question bundles that the production API can serve. Each bundle must be answerable, attached to an existing production topic and subtopic, and supported by evidence that meets an explicit trust policy. Sources and AI models are providers at the edges. The core pipeline is fixed, predictable and testable. A new source or model is added by implementing a provider contract, not by editing the pipeline.

The user's constraint is the foundation: questions are not invented. Every question comes from a source and belongs to the researched production catalog. The source supplies the question, options, answer and whatever is needed to answer it, such as a passage or an image. The factory classifies it against the catalog, explains it and verifies it. Nothing else is allowed to invent a topic, a subtopic, an answer or a missing stimulus.

### 1.1 What "ready" means

A ready row must satisfy all of these:

1. The mechanical gate passed.
2. The source provenance is recorded.
3. The exam, subject and year map to the production catalog.
4. The subtopic exists in the production catalog at the catalog version used for the run.
5. Every linked passage exists as a passage row.
6. Every required figure exists as a stored media asset, and its image has been read and described.
7. The explanation is present and structurally valid.
8. The content bundle has a hash that covers the question, options, answer, marks, explanation, passage and media evidence.
9. The latest verification required by the trust policy is a pass whose hash still matches the bundle.
10. That verification exists in the lane the API reads.
11. The production predicate in `src/store/catalog.rs:236` returns true for the row.

The current systems enforce pieces of this in different places. None enforces the whole definition at the point of promotion.

### 1.2 The content envelope

The API does not serve a row. It serves a bundle. Treat the bundle as the unit that moves through the pipeline:

```text
ContentBundle
  source:
    provider, source_url, source_item_id, fetched_at, payload_hash, source_version
  catalog:
    exam, subject, year, section, marks, topic_id, subtopic_id, catalog_version
  content:
    stem, options, answer, inline marks, passage, media assets, explanation
  evidence:
    gate verdict, media descriptions, AI proposals, verifications, review decisions
  state:
    lane, attempts, errors, promotion record
  bundle_hash
```

The bundle is why the current seam fails. The bank moves questions and passages between work and ready, but not verifications. The pipeline moves questions to production, but not verifications. Both systems treat the bundle as separate rows with separate lifecycles. Promotion must move the bundle and its deciding verification together, or verification must be written in the lane the API reads. One invariant, enforced in one place.

### 1.3 The provider model

The provider model is the right direction. It needs to be narrower and more explicit than a class with a `crawl` method.

**Source provider.** Declares what it can supply, for which exams, subjects and years. It probes coverage, fetches source items, maps them to the production scope, and records provenance. It does not tag, explain or verify.

**Model provider.** Declares modalities, context limit, structured output support, cost, latency and rate limit. It exposes capabilities such as tagging, explanation, answer verification, image description and mark extraction. It does not write to the database. It proposes, and the core validates.

**Media provider.** Fetches, hashes, stores and serves assets. It can verify reachability and MIME type. A vision model may describe the asset, but the media provider owns the asset record.

**Catalog provider.** Reads exams, subjects, topics, subtopics, blueprints and scope from production. It returns a versioned snapshot so every stage in a run sees the same catalog.

**Review provider.** Lists work, shows a bundle, records a decision and writes a trusted verification. A human CLI and an agent surface can both implement it. The credential decides whether the decision may count as human or AI.

**Content store.** Owns lanes, atomic bundle writes and the verification log. It is the only component that writes content.

**Evaluator.** Runs providers against gold sets and writes scorecards. A provider is eligible for a task only when its scorecard meets the policy threshold.

The core is the fixed sequence that calls these providers. The model never calls the store directly. The model never invents a slug, a mark or a verification kind that the core has not allowed.

### 1.4 Non-goals

The factory is not trying to replace the API, the reference catalog or the media CDN. It is not trying to invent questions, topics or subtopics. It is not trying to auto-accept model judgement before that judgement has a measured scorecard. It is not trying to preserve every helper from `tools/` or every module in `utmelab-pipeline/`.

## 2. What is true today

| System | What passes | What it proves |
|---|---|---|
| Bank unit suite | Green, last run reported 82.24 percent coverage | Individual functions behave as their tests expect |
| Bank chain test | `tests/test_intake.py:225` promotes a row | Promotion returns success |
| Bank workflows | `bank-ingest` stops after dedupe; `bank-enrich` stops after `ai-verify` | No automated path reaches ready |
| Pipeline unit suite | Green | Individual functions and mocked flows behave as their tests expect |
| Pipeline sync test | `tests/test_sync_prod.py` checks a question lands in production | It does not check that production can serve it as verified |
| Pipeline roadmap | Claims all phases complete and production ready | Unsupported by the acceptance predicate |
| Production predicate | Requires a latest human pass over answer and explanation with a matching hash | Neither system evaluates it end to end |

Both systems can report success while the production reader returns `verified: false`. That is the central fact of this review.

## 3. The common failure

### 3.1 The bank

`promote_one` at `src/utmelab_bank/task/promote.py:90-99` copies the passage and the question into ready. It never copies verifications. `ai-verify` writes `kind='ai_verify'` in work. The production predicate reads only `kind='human'`. A human pass written through the workbench also stays in work. The ready lane therefore has no deciding human verification.

`promote_one` also does not require the gate, the explanation, a real passage row or a human pass. It writes `gate_status='pass'` unconditionally. The default `where='gated'` is a caller convention, not an invariant.

### 3.2 The pipeline

`ProductionSyncEngine.validate_and_sync` at `utmelab-pipeline/pipeline/orchestrator/sync_prod.py` validates that an `approved_verifications` row exists. When it writes to production, it inserts passages and questions. It never inserts into production `verifications`.

The approved verification is also the wrong shape. `PipelinePromoter.promote` writes `kind='ai_bulk'` and `scope='["answer", "subtopic"]'`. The API requires `kind='human'`, a verdict of pass, a matching hash and a scope containing `answer` and `explanation`. Even if sync copied that row, the API would ignore it.

The pipeline's auto-promotion path is therefore doubly broken. It cannot produce a servable verified row, and its trust semantics conflict with the current API contract.

### 3.3 The root cause

Both systems are row-oriented. The bank has a lane for questions, a lane for passages and a lane for verifications, and no atomic bundle promotion. The pipeline has staging, approved questions, approved passages and approved verifications, and no production verification sync.

The tests stop at stage boundaries. The bank promotes and asserts success. The pipeline syncs a question and asserts the row exists. Neither applies the production predicate. A green suite is compatible with a red product.

## 4. Bank findings

Severity is relative to the objective in section 1. "Fatal" means the bank cannot reach the objective while the finding holds. "High" means a class of questions is wrong or unrecoverable. "Medium" means the work is slower or harder to trust. "Low" means a narrow defect.

### F1. Promotion drops verifications

**Severity:** fatal.

**Where:** `src/utmelab_bank/task/promote.py:90-99`, `src/utmelab_bank/task/ai/verify.py`.

**What happens:** promotion inserts the passage and the question. It never reads or inserts `verifications`. A human pass in work stays in work.

**Why it matters:** the API requires a human pass in the lane it reads. A ready row with no ready verification is not served as verified. This is the main reason the bank is not production ready despite green unit tests.

**Tools comparison:** `tools/review.py:381-407` appended a human pass directly to the live bank. There was no lane boundary and no copy step. The bank created the boundary and left the obligation unimplemented.

**Fix direction:** promotion must copy the deciding human verification rows with the bundle, or verification must run against the ready lane after promotion. Pick one invariant and enforce it in one place. Copying at promotion keeps ready self-contained.

### F2. Promotion admits rows it should refuse

**Severity:** fatal.

**Where:** `src/utmelab_bank/task/promote.py:73-99`, `src/utmelab_bank/task/promote.py:146-151`.

**What happens:** `promote_one` checks only for a content hash and an existing ready row. It does not check `gate_status`, the explanation, passage existence, subtopic validity or verification. It then writes `ready["gate_status"] = "pass"` unconditionally. The docstring claims three conditions are checked, but the gate is not one of them. `require_promotable` exists but nothing calls it except tests, and it checks only the gate and hash.

**Why it matters:** the default selector is `gated`, so most callers promote gated rows by convention. A caller that passes `where="all"` can promote an ungated row, a row with no explanation, a row with a dangling passage link or a row with no human pass. The ready lane's guarantee depends on caller discipline, not on the task.

**Tools comparison:** `tools/review.py:381-407` refused a flagged row, a missing explanation and a missing passage. The bank's review helper does the same checks, but promotion bypasses them.

**Fix direction:** one `assert_promotable` used by `promote_one` and the review command. It should require gate pass, hash, explanation, subtopic, passage row when linked, media evidence when required, and the latest trusted verification. The gate status should be copied only after the check.

### F3. No workflow reaches ready

**Severity:** fatal.

**Where:** `.github/workflows/bank-ingest.yml`, `.github/workflows/bank-enrich.yml`.

**What happens:** `bank-ingest` runs `fill`, `intake`, `gate` and `dedupe`. `bank-enrich` runs `ai-tag`, `ai-explain`, `ai-verify` and the media steps. Neither runs `promote`. `pipeline.yml` calls the separate pipeline system.

**Why it matters:** even after F1 and F2 are fixed, the automated path stops in work. A human must remember to run promotion manually, and no workflow verifies that ready is servable.

**Tools comparison:** the old workflows operated on one bank, so there was no distinct promotion stage to forget. The bank's lane design added the stage and omitted it from the pipeline.

**Fix direction:** add promotion to a finalize workflow after the trust gate, or add a `bank-finalize` goal that promotes and then checks the production predicate. The workflow should fail when the ready count and the verified count disagree.

### F4. Default acquisition drops passages

**Severity:** fatal for comprehension and data-block questions.

**Where:** `src/utmelab_bank/source/myschool/parser.py:558`, `src/utmelab_bank/source/myschool/run.py:65`, `src/utmelab_bank/fill.py`, `.github/workflows/bank-ingest.yml`, `src/utmelab_bank/rules.py:205`.

**What happens:** `parse_api_question` builds a question from the listing payload and never attaches a passage. `fetch_via_api` never fetches the detail page. `fill` defaults to the API strategy, and `bank-ingest` uses that default. The API fixture row has keys `collection`, `id`, `image`, `novel_id`, `options`, `question` and `ref_id`. It has no `passage`, `ref` or passage text. A detail request is required.

The HTML route extracts passages in `parse_detail`, but no workflow uses it. `fetch_via_html` defaults to one listing page at `run.py:147`, and `fill --strategy html` does not pass a page count, so the bulk command would also stop after one page.

The gate makes the problem worse. `has_passage` is `bool(row.get("passage_id"))` at `rules.py:205`. A row that announces a passage but has no passage row is rejected. A row that depends on a passage without naming it can pass with no passage at all.

**Why it matters:** comprehension, cloze and data-block questions cannot be answered or verified without the stimulus. The bank produces rows that look gated and tagged but are incomplete.

**Tools comparison:** `tools/harvest.py` fetched the detail page and extracted passages before writing the bank. The bank has the parser but does not call it by default.

**Fix direction:** fetch detail when the source provides a reference or when the listing suggests a stimulus, or add a passage backfill stage before intake. Do not rely on the stem to announce its needs; that is wording, not data.

### F5. Verification semantics disagree with the API

**Severity:** high.

**Where:** `src/utmelab_bank/task/review/verify.py:53-72`, `src/utmelab_bank/store/selectors.py:552-563`, `src/store/catalog.rs:236-248`.

**What happens:** the bank's `is_verified` scans newest first, skips nonmatching hashes and nonpass rows, and returns true on any older human pass with the needed scope. The API rule is that the latest human verification carrying `answer` and `explanation` must itself be a pass with a matching hash. If the latest human row is a fail, the API says unverified even when an older pass exists. The bank says verified.

The `unverified` selector has the same mismatch. It uses `NOT EXISTS` for any human pass. A row with a latest fail and an older pass is not selected. `write_verification` calls `is_verified` first, so it can refuse to let a reviewer write a fresh pass after a fail.

**Why it matters:** the bank can promote a row that production will not serve, and it can lock a reviewer out of correcting it. This is a regression from the tools.

**Tools comparison:** `tools/review.py:109-121` implements the correct rule. It filters to human rows covering answer and explanation, sorts by `(created_at, id)`, takes the last row, and requires that row to be a pass with a matching fingerprint.

**Fix direction:** one `latest_human_verification` helper used by `is_verified`, the `unverified` selector, the review command and promotion. Sort by `(created_at, id)`.

### F6. Review has no operator interface

**Severity:** high.

**Where:** `src/utmelab_bank/task/review/`, `src/utmelab_bank/task/__init__.py`, `README.md:128`.

**What happens:** the review package contains a bundle builder, `next_id`, `set_fields` and `write_verification`. None is exposed through the CLI. `task/__init__.py` does not import `task.review`, and `all_tasks()` does not list a review task. The README lists `review` as the stage where a human settles what the model would not, but there is no `bank review` command.

**Why it matters:** the human step in the documented lifecycle cannot be performed through the product. A reviewer would have to write Python against the package. The AI verify task writes an `ai_verify` row, but promotion does not read it.

**Tools comparison:** `tools/review.py` had `show`, `next`, `verify`, `set`, `stats`, `--json`, backup and rollback.

**Fix direction:** add `bank review show|next|set|verify|stats`, with `--json`. Allow a human to record a fail, not only a pass. Use the latest-human rule.

### F7. `ai-tag` discards the underline

**Severity:** high for rows with an underline.

**Where:** `src/utmelab_bank/task/ai/tag.py:122-127`, `src/utmelab_bank/task/ai/tasks.py:33-50`.

**What happens:** `tag_question` returns a `TagResult` with the underline word, start and length. `tag_one` writes only `subtopic_id`. It does not apply the underline to `inline`, and it does not persist `answer_verified`. It also skips any row that already has a subtopic, so it cannot revisit a tagged row to add an underline.

**Why it matters:** the underline is required for a large class of English questions. The snap logic exists and works. The bank throws the result away. A row without an underline can only be fixed through the unexposed `set_fields` path.

**Tools comparison:** `tools/utmetag` produced the underline in its results. The old workflow uploaded the results and a separate step applied them. The bank calls the model but does not apply its underline.

**Fix direction:** apply the underline in `ai-tag` when the model returns one, or add an `ai-underline` task that revisits rows with a subtopic but no underline. Keep the snap behavior.

### F8. Figures duplicate and ad images survive

**Severity:** high.

**Where:** `src/utmelab_bank/source/myschool/parser.py:248`, `parser.py:423`, `parser.py:620`.

**What happens:** `parse_detail` builds inline marks from the raw HTML with `clean_inline`, which emits an image mark for every `<img>` in the stem. It then appends every URL from `question_images` to the same marks. `question_images` filters ad paths and deduplicates its own list, but it does not know which images `clean_inline` already emitted. A figure that appears as an `<img>` in the stem is anchored twice. `_inline_figure_urls`, which looks like the intended reconciliation point, is a stub that returns `[]`. The API path also appends `row["image"]` without checking whether the markup already contains it. `clean_inline` has no ad filter, so an ad image inside the stem region survives as an inline mark.

**Why it matters:** a question with one figure can render two copies. An ad banner can reach the question and the media pipeline. `media-discover` then finds both and fetches both.

**Tools comparison:** `tools/harvest.py` filtered ad assets and deduplicated image URLs before writing.

**Fix direction:** collect the image URLs already present in inline marks before appending discovered images. Filter ad assets in `clean_inline` as well as `question_images`. Add a parser test with one clean figure, one duplicate and one ad image.

### F9. No passage recovery or backfill

**Severity:** high.

**Where:** `tools/recover_passages.py`, `src/utmelab_bank/store/selectors.py`.

**What happens:** the bank has no task or selector for rows missing a passage. It can carry a passage during intake if the raw row has one, but it cannot go back to raw HTML or a detail page to repair rows already ingested without one.

**Why it matters:** once the default API route writes rows without passages, those rows are stuck. Re-running the same route will not help.

**Tools comparison:** `tools/recover_passages.py` walked raw HTML, refetched missing pages, grouped passages and wrote them back. It made six previously unanswerable rows answerable.

**Fix direction:** add a `passages` repair task idempotent by passage id. Read raw first and refetch detail only when raw is absent. Add a `no-passage` selector.

### F10. No bulk probe

**Severity:** medium.

**Where:** `tools/harvest_all.py`, `src/utmelab_bank/fill.py`.

**What happens:** the bank can dry-run one subject's fill plan or one scrape. It cannot count a subject-year across the catalogue without fetching listings.

**Why it matters:** the operator cannot see coverage or choose where to spend detail fetches and model calls.

**Tools comparison:** `tools/harvest_all.py --probe` counted subject-years and produced a plan.

**Fix direction:** add `bank probe --exam ... --subject ...` that uses the listing count and writes a report. It should make no detail requests and write no rows.

### F11. No duplicate audit

**Severity:** medium.

**Where:** `tools/dup_audit.py`, `src/utmelab_bank/store/selectors.py`.

**What happens:** the bank refuses exact duplicates at write time and checks production hashes before acquisition. It cannot report duplicates already present in work or ready, and it cannot fail CI on them. It has no buckets for shared text with different keys or same-key rows with different figures.

**Why it matters:** an exact duplicate is noise, while a same-stem row with a different answer key is a correctness problem. Without a report, the operator cannot tell which is which.

**Tools comparison:** `tools/dup_audit.py` produced exact, shared and same-key buckets and a `--strict` exit code.

**Fix direction:** add `bank audit duplicates --json` and `--strict`, read-only, using the same keys as dedupe.

### F12. AI tasks run serially

**Severity:** medium.

**Where:** `src/utmelab_bank/task/base.py:368`, `src/utmelab_bank/task/ai/`.

**What happens:** `gather_bounded` exists but is unused. Each AI task processes one row at a time. The old utmetag runner defaulted to concurrency 3.

**Why it matters:** the bank has 40 subjects and hundreds of rows per subject. Serial model calls make enrichment slow enough that an operator is tempted to skip it or run it outside the workflow.

**Tools comparison:** `tools/utmetag/runner.py` bounded concurrency at 3 and preserved result order.

**Fix direction:** use `gather_bounded` in the AI tasks with a configurable limit and deterministic output order. Isolate per-row failures.

### F13. No bulk underline worksheet

**Severity:** medium.

**Where:** `tools/propose_emphasis.py`, `src/utmelab_bank/task/review/`.

**What happens:** the review helper can set one underline on one row, but there is no CLI and no worksheet. There is no `next` filter for rows without an underline and no bulk apply.

**Why it matters:** underline work is a large human pass. One row per command is too slow, and the AI underline is discarded.

**Tools comparison:** `tools/propose_emphasis.py` proposed underlines into a worksheet and applied reviewed answers.

**Fix direction:** add `bank review underlines propose|apply`, writing a CSV or JSON worksheet. Validate that the underline is a non-empty substring and replace existing underline marks rather than stacking them.

### F14. No curated drop or explanation edit

**Severity:** low, but needed during repair.

**Where:** `tools/drop_rows.py`, `tools/write_recovered_explanations.py`, `src/utmelab_bank/task/review/`.

**What happens:** the bank cannot drop a curated row with a twin guard, and it cannot edit an explanation through the review surface. `set_fields` handles scalar fields, not explanation text.

**Why it matters:** recovery work needs a written explanation for a row whose passage was just recovered. Without an edit path, the operator writes ad hoc Python or edits the database.

**Tools comparison:** `tools/drop_rows.py` refused to drop a row while a twin remained. `tools/write_recovered_explanations.py` wrote six curated explanations and refused rows without a passage.

**Fix direction:** add `bank review drop --reason` with a twin check, and `bank review explain --file` or an interactive edit. Recompute the bundle hash after an explanation change.

### F15. `source_url` uses the raw subject name

**Severity:** low.

**Where:** `src/utmelab_bank/source/myschool/parser.py:558`.

**What happens:** `parse_api_question` builds the source URL with `catalog["subject"]`, not with `slug_for`. If the label and slug differ, the URL points at the wrong path and the provenance key differs from the HTML route.

**Why it matters:** broken source links make review harder, and inconsistent provenance can create two identities for one question.

**Fix direction:** use `slug_for` in both routes. Add a fixture where the label and slug differ.

### F16. The HTML route under-fetches

**Severity:** medium.

**Where:** `src/utmelab_bank/source/myschool/run.py:147`, `src/utmelab_bank/fill.py:198`.

**What happens:** `fetch_via_html` defaults to one listing page. `fill` accepts `--strategy html` but builds its `FetchRequest` without a page count, so the HTML route stops after the first page. `scrape` has `--pages`, but `fill` does not.

**Why it matters:** the route that carries passages cannot cover a subject when run through the bulk command.

**Fix direction:** give `fill` a page count and pass it into `FetchRequest`, or have the HTML route read the listing's reported total. Wire one workflow to the HTML route for a passage-heavy subject so the path stays tested.

### F17. Dangling passage links pass intake and promotion

**Severity:** high.

**Where:** `src/utmelab_bank/rules.py:205`, `src/utmelab_bank/task/intake.py`, `src/utmelab_bank/task/promote.py:93-98`.

**What happens:** the gate checks that `passage_id` is present, not that the passage row exists. Intake copies the ID even if the raw passage is missing. Promotion looks up the passage, but if `found` is empty it proceeds with the question anyway.

**Why it matters:** the API resolves `passage_id` to null or fails the join. The question is unanswerable even though the bank reports a gated, promoted row.

**Fix direction:** the gate should check the passage row, not the ID. Intake should refuse or clear a dangling link. Promotion should refuse when a linked passage is missing.

### F18. Passage and media edits do not invalidate verification

**Severity:** high.

**Where:** `ROADMAP.md`, `src/utmelab_bank/model/hash.py`, `src/utmelab_bank/task/review/verify.py:40-50`.

**What happens:** `content_hash` covers the stem, options, answer, marks and explanation. It does not cover passage text or media evidence. A human can verify a comprehension row, then someone can edit the passage, and the verification still matches. The bank's `needed_scope` adds `passage`, but the hash does not include passage content, so the scope label alone does not detect the edit.

**Why it matters:** a verified row can become wrong without a signal.

**Fix direction:** decide the hash contract before changing it. Either fold passage and media evidence into the bundle hash, or add a passage/media hash to the verification and check it in the API predicate. Do not silently ignore the gap.

### F19. Verification ordering has no tie-breaker

**Severity:** low.

**Where:** `src/utmelab_bank/task/review/verify.py:33-37`.

**What happens:** `verifications_for` sorts by `created_at` only. The API sorts by `(created_at, id)`. Two rows with the same timestamp can order differently.

**Why it matters:** the bank and the API can disagree about which human row is latest.

**Fix direction:** sort by `(created_at, id)` in the bank helper.

### F20. Promotion is not atomic

**Severity:** low.

**Where:** `src/utmelab_bank/task/promote.py:90-99`.

**What happens:** the passage insert and the question insert are separate operations with no transaction. A crash between them leaves an orphan passage.

**Why it matters:** a database gives no reason to keep the old JSON backup discipline. The failure is rare, but the repair is manual.

**Fix direction:** wrap the bundle writes in one transaction if the repository exposes one. Add a cleanup selector for unreferenced ready passages.

## 5. Pipeline findings

The pipeline has good ideas and the same fatal seam. These findings are about the code, not the specification documents, which claim more than the code does.

### P1. Production sync never writes verifications

**Severity:** fatal.

**Where:** `utmelab-pipeline/pipeline/orchestrator/sync_prod.py`.

**What happens:** `validate_and_sync` checks that an `approved_verifications` row exists with a matching hash. It then writes passages and questions to production. It never inserts into production `verifications`.

**Why it matters:** the production API derives `verified` from the verification table. A synced question returns `verified: false`. The pipeline's roadmap calls this "ALL PHASES COMPLETE & PRODUCTION READY"; the code does not support that claim.

**Test gap:** `tests/test_sync_prod.py` asserts the question row exists. It never queries production `verifications` or applies the API predicate.

### P2. Approved verifications have the wrong kind and scope

**Severity:** fatal.

**Where:** `utmelab-pipeline/pipeline/orchestrator/promoter.py:223-235`.

**What happens:** the promoter writes `kind='ai_bulk'` and `scope='["answer", "subtopic"]'`. The API requires `kind='human'`, `verdict='pass'`, a matching hash, and a scope containing `answer` and `explanation`.

**Why it matters:** even if P1 were fixed by copying this row, the API would ignore it.

**Fix direction:** the verification writer must produce the exact kind and scope the API accepts. If AI is trusted, that is a new API contract, not a mislabeled human row.

### P3. Auto-approval bypasses the trust policy

**Severity:** fatal for the current API semantics.

**Where:** `utmelab-pipeline/pipeline/orchestrator/worker.py:110-120`, `pipeline/storage/repository.py:145-160`.

**What happens:** a row is marked `auto_approved` when `answer_check == "VERIFIED"` and `confidence >= 0.85`. It is then promoted with the model's subtopic slug. There is no independent verification, no catalog validation at promotion, no human pass and no measured provider qualification.

**Why it matters:** the old decision D45 says `verified` means a human checked the answer and explanation. D62 says only `Human/Pass` over answer and explanation sets the bool; AI rows are signal, never a pass. The pipeline's auto-approval contradicts both. It cannot currently satisfy the API, and if it could, it would be claiming a review that never happened.

**Fix direction:** separate `candidate` from `verified`. Auto-promotion to a candidate queue is fine. A trusted policy decides whether the row becomes servable. The policy can become AI-only later, after measured precision and an explicit API decision.

### P4. No independent accuracy evaluation

**Severity:** high.

**Where:** `utmelab-pipeline/pipeline/ai/`, `utmelab-pipeline/tests/`.

**What happens:** the only quality signal is the model's self-reported `confidence`. There is no gold set, no held-out evaluation, no per-subject or per-task accuracy, no calibration, no provider scorecard and no precision measurement on auto-promoted rows.

**Why it matters:** the user's target is 90 to 100 percent success before removing human review. Self-confidence is not evidence. A model can be confident and wrong, especially on diagrams and ambiguous keys.

**Fix direction:** build an evaluation harness with stratified gold sets and scorecards. Auto-promotion is allowed only for a provider and task that meet a measured precision threshold with an acceptable abstention rate.

### P5. Source plugins are duplicated scrapers, not a provider contract

**Severity:** high.

**Where:** `utmelab-pipeline/pipeline/sources/jamb.py`, `waec.py`, `neco.py`, `sources/__init__.py`.

**What happens:** JAMB, WAEC and NECO are three near-identical copies of the same myschool HTML scraper. The differences are a URL parameter and an exam label. Subject slug maps are hardcoded in two classes. The registry is a static dictionary. There is no source profile, capability declaration, coverage probe, source-specific validation or contract test.

**Why it matters:** adding a genuinely different source is not simple. The user's requirement is that a new source is a plugin with a defined scope. Three copies of one source is the opposite.

**Fix direction:** model `myschool` as one source provider with an exam scope. Add `SourceProfile`, `probe`, `fetch`, `adapt`, `validate` and `health`. A different source implements the same contract. The registry discovers providers, not hardcoded classes.

### P6. One media URL and no media evidence

**Severity:** high.

**Where:** `utmelab-pipeline/pipeline/sources/base.py`, `pipeline/gates/media_check.py`, `pipeline/orchestrator/worker.py`.

**What happens:** `RawQuestionPayload` has a single optional `media_url`. The gate checks only that the field is present. `check_media_reachability` exists but is not called by the harvest CLI. The media downloader caches the image for the model, but the asset is not stored as a media record, hashed, described or linked as evidence. Option images and multiple figures are not represented.

**Why it matters:** an image-dependent question is useless if the image cannot be fetched or read. The user's point is exact: if the system cannot see or describe the image, it cannot tag or verify the question. A URL string is not evidence.

**Fix direction:** media is a first-class asset with a hash, MIME type, dimensions, storage URL and image description. Gate on reachability. Vision describes the asset. Verification cites the description. Rows with required but unreadable media do not promote.

### P7. Rich text is flattened

**Severity:** high.

**Where:** `utmelab-pipeline/pipeline/sources/jamb.py`, `pipeline/ai/tasks.py`, `pipeline/orchestrator/promoter.py`.

**What happens:** the scrapers strip HTML into plain stem and option text and preserve only an underline offset. They do not map bold, italic, strike, subscript, superscript, images or paragraph breaks. Promotion builds `RichText` with plain strings and a single image mark. Passages are stored with `inline='[]'`.

**Why it matters:** the Rust API's D60/D61 contract expects one `RichText` shape for every text field, with validated marks and `\n\n` for passages. Flattening loses underlines, emphasis, chemistry notation and figure placement. It also makes the content hash differ from a faithful source representation.

**Fix direction:** one `richtext` normalizer used by every source. It maps tags to marks, preserves paragraph breaks in passages, validates Unicode offsets and non-overlap, rejects raw HTML and keeps text plain. Add a fixture corpus of source HTML to expected marks.

### P8. Passages are duplicated and unshared

**Severity:** high.

**Where:** `utmelab-pipeline/pipeline/orchestrator/promoter.py:170-200`.

**What happens:** promotion creates a passage per staging row from `passage_raw`, using a hash of the text. Five comprehension questions on one passage each carry the same text and create or replace the same passage id. The passage `inline` is hardcoded to `[]`, so formatting is lost. The source model has no shared passage identity.

**Why it matters:** the API resolves one passage for a set. Duplicating the text per row wastes space, loses marks and makes a passage edit a multi-row repair.

**Fix direction:** the source adapter should identify a passage set, or the normalizer should group rows by source passage identity. The bundle carries a passage reference. Promotion writes the passage once and links every question to it.

### P9. Subtopic validation happens late or not at all

**Severity:** high.

**Where:** `utmelab-pipeline/pipeline/ai/prompts.py`, `pipeline/orchestrator/worker.py`, `pipeline/orchestrator/sync_prod.py`.

**What happens:** the prompt gives the model a list of subtopics and says not to invent one. The worker writes the returned `subtopic_slug` without checking it against the list. `sync_prod` rejects an unknown slug at the end, after the AI work is spent. The bank has the same missing task-level validation; its `ai-tag` writes the returned slug directly.

**Why it matters:** a hallucinated slug is a failed row that looked successful for most of the pipeline. The user's core rule is that every question belongs to an existing production topic and subtopic.

**Fix direction:** the tag output is a constrained choice, not free text. Validate against the exact catalog snapshot before writing. An unknown slug is a task failure, not a late sync failure. Store the catalog version with the bundle.

### P10. Review is read-only

**Severity:** high.

**Where:** `utmelab-pipeline/pipeline/cli.py:189-220`.

**What happens:** the CLI has `review list` only. The docs promise `review resolve`, but there is no command and no `write_verification` path. The review queue is a report, not a workbench.

**Why it matters:** the pipeline's exception path cannot resolve an exception. The only path is auto-approval, which is exactly the path that cannot satisfy the API.

**Fix direction:** add `review show`, `review next`, `review set`, `review verify` and `review stats`, with a human pass writer. Use the latest-human rule and the bundle hash.

### P11. Provenance is hardcoded

**Severity:** medium.

**Where:** `utmelab-pipeline/pipeline/orchestrator/promoter.py`.

**What happens:** every approved question is written with `source='claimed_paper'`. The source name, source URL, source item id and fetch time live in staging but are not carried into the approved row.

**Why it matters:** the user's definition of a source is where the question came from. Losing provenance makes audit, re-fetch and repair impossible. It also makes two sources indistinguishable.

**Fix direction:** carry the source block into the bundle and the approved/production row. `source` should name the provider, not a generic label.

### P12. Dedupe checks staging only

**Severity:** medium.

**Where:** `utmelab-pipeline/pipeline/storage/repository.py:65-70`.

**What happens:** `is_fingerprint_staged` checks `harvest_staging` only. The docs claim production `content_hash` is checked. It is not. A question already in production can be harvested and processed again.

**Why it matters:** duplicate AI spend and duplicate content. The bank does check production hashes, which is one of its strengths.

**Fix direction:** dedupe against staging, approved and production. Use the same normalized key and the same content hash as the API.

### P13. Gate checks presence, not reachability

**Severity:** medium.

**Where:** `utmelab-pipeline/pipeline/gates/mechanical.py`, `pipeline/gates/media_check.py`, `pipeline/cli.py`.

**What happens:** the gate requires a `media_url` when the stem references a figure, but it does not fetch it. `check_media_reachability` exists and is not called. A dead or non-image URL passes Gate 0.

**Why it matters:** the model later fails to open the image, and the row is flagged late or silently loses its figure.

**Fix direction:** call reachability at the gate or in a media stage before AI. Store the fetched asset and hash, not just the URL.

### P14. Promotion and sync are not atomic

**Severity:** medium.

**Where:** `utmelab-pipeline/pipeline/orchestrator/promoter.py`, `pipeline/orchestrator/sync_prod.py`.

**What happens:** questions, passages and verifications are written with separate `INSERT OR REPLACE` statements. A failure can leave a question without its passage or verification. Sync writes questions and passages, not verifications, so the bundle is incomplete by design.

**Why it matters:** partial bundles are worse than missing rows because they look present.

**Fix direction:** one transaction per bundle. Promotion writes the question, passage, media link and verification together. Sync either writes the full bundle or writes nothing.

### P15. The workflow is not autonomous

**Severity:** medium.

**Where:** `.github/workflows/pipeline.yml`.

**What happens:** the workflow is a single manual dispatch with an `action` choice. Harvest, process, promote and sync are separate runs. The docs describe a matrix, but the workflow is one job. There is no plan that runs a scope from source to production and reports the end-to-end result.

**Why it matters:** the user's goal is a pipeline that can run itself. Manual stage dispatch is not that. It also makes it easy to stop after processing and never sync.

**Fix direction:** one `run` command that plans scopes, harvests, gates, processes, evaluates, promotes and audits, with a run manifest and resumability. Matrix jobs can execute the plan, but the manifest is the contract.

### P16. Contract tests do not test the contract

**Severity:** high.

**Where:** `utmelab-pipeline/tests/test_sync_prod.py`, `tests/test_promoter.py`.

**What happens:** the tests assert that rows land in pipeline approved tables and production questions. They do not apply the production verification predicate, do not check scope/kind, and do not assert that the API would serve `verified: true`. The parity test checks a handful of hashes against old data.

**Why it matters:** the exact failure that matters is invisible to the suite. This is the same pattern as the bank.

**Fix direction:** the contract test must execute the production predicate against the target database and assert the served shape. A question row without a valid verification must fail the test.

## 6. Tools comparison

| Tool | What it did | Bank status | Pipeline status | Gap |
|---|---|---|---|---|
| `tools/harvest.py` | Detail pages, passages, figures, ad filtering, mark dedupe | Detail parser exists; default API route loses passages; marks duplicate | Detail scraping exists; only one media URL; marks flattened | No single faithful source-to-RichText path |
| `tools/harvest_all.py` | Bulk harvest, probe, resume, flush | One subject at a time; no probe | One subject at a time; no probe | No catalogue planning |
| `tools/recover_passages.py` | Raw and detail passage backfill | No equivalent | No equivalent | No repair path |
| `tools/review.py` | `show`, `next`, `verify`, `set`, `stats`, `--json`, backup | Logic only, no CLI | `review list` only | No operator workbench |
| `tools/dup_audit.py` | Exact, shared, same-key audit with `--strict` | Write-time refusal only | Staging fingerprint only | No read-only audit |
| `tools/drop_rows.py` | Curated drop with twin guard | No equivalent | No equivalent | No safe removal |
| `tools/propose_emphasis.py` | Bulk underline worksheet | Per-row helper only | No equivalent | No bulk underline work |
| `tools/write_recovered_explanations.py` | Curated explanations | No equivalent | No equivalent | No human explanation edit |
| `tools/auto_verify_opencode.py` | Legacy auto-accept verifier | Correctly not ported | Pipeline auto-approves on confidence | Auto-accept is still present in a different form |
| `tools/auto_tag_questions.py`, `tools/utmetag` | Bulk tagging, underline output, concurrency 3 | Tag writes subtopic, discards underline, serial | Tag and verify in one call, serial per subject pool | Underline and independent passes missing |
| `tools/import_syllabus.py` | Imported syllabus | Replaced by production reference reader | Reads production syllabus | Keep removed |

The tools are not a target to copy wholesale. `auto_verify_opencode.py` auto-accepted model judgement and is reported to be buggy. `import_syllabus.py` is deliberately gone because the production catalog is the authority. The useful parts are operational: detail acquisition, passage recovery, review, audit, underline worksheet and concurrency.

## 7. What is worth keeping

### 7.1 Bank

- The gate is broad and runs before writes. It covers options, answer keys, stems, figure hints, underlines, novel leaks and stimulus hints.
- Content hashing is centralized and shared with the production predicate.
- The work and ready lanes make the lifecycle explicit.
- Deduplication checks production hashes.
- The reference reader replaces a copied syllabus with production data.
- The media pipeline discovers, fetches, uploads and verifies assets.
- Promotion is the only task allowed to write ready.
- AI verification does not auto-accept.
- The code is typed, tested and has contract checks.

### 7.2 Pipeline

- `RawQuestionPayload` and `BaseHarvester` are a starting point for a source contract.
- The detail scraper extracts passages, which the bank's default API route does not.
- The stdin plus image attachment pattern for OpenCode is proven and worth keeping.
- Gate 0 has figure and passage hints.
- The dedicated staging database, review queue and dry-run sync are sound operational ideas.
- The content hash parity test against real data is valuable.
- Bounded concurrency is already designed.
- The syllabus is read from production at runtime.

### 7.3 Old decisions

- D45: `verified` means reviewed, not sourced.
- D62: the verification log is the store; only a human pass over answer and explanation sets the bool; AI rows are signal.
- D60 and D61: every text field is `RichText`, with validated marks and `\n\n` for passages.
- D16 and D50: the production catalog is the authority; do not invent topics, subtopics or weights.
- D35: novels are a separate domain.
- D64: the database schema mirrors the API structs; verified is derived, not stored.

The old decisions are not obsolete. They explain why the current seams are wrong.

## 8. Why this happened

**The tools had one bank and a human at the end.** Harvest, review and verification touched the same JSON file. There was no lane boundary and no copy step. The old human could run `tools/review.py verify` and the verification sat next to the question.

**The new systems split the bundle into rows.** The bank split work and ready. The pipeline split staging, approved questions, approved passages and approved verifications. Both splits are reasonable for state management. Both forgot that the API consumes a bundle, not a row. Promotion copied some rows and not others.

**The tests stop at task boundaries.** A unit test can prove that promotion returns `ok`. A sync test can prove that a question row exists. Neither proves that the API would serve the row as verified. The exact failure lives between the tests.

**Automation was added before the trust contract was settled.** The pipeline's auto-approval and the bank's `ai_verify` both assume that a model pass is close enough to a human pass. The API says otherwise. The result is a system that can move rows quickly to a place where they are not servable.

## 9. Target architecture

### 9.1 One factory, providers at the edges

Do not keep two Python factories. The bank and the pipeline duplicate sources, gates, AI calls, promotion and tests. Pick one core and make the other a donor. My recommendation is the bank as the base, because its domain model, gate, reference reader, media pipeline and tests are stronger. Port the pipeline's source adapter, multimodal prompt, metrics and dry-run ideas into it. Archive the pipeline after parity.

The core is a fixed sequence:

```text
plan -> acquire -> normalize -> gate -> dedupe -> resolve catalog
     -> tag -> describe media -> explain -> verify -> policy
     -> promote -> audit
```

Providers sit at the edges of that sequence. The sequence does not import a specific source, model, media host or store. It imports ports.

### 9.2 Source contract

A source provider publishes a profile and implements four operations:

```python
class SourceProfile:
    name: str
    version: str
    exams: list[str]
    subjects: dict[str, str]        # source subject -> production slug
    years: tuple[int, int] | None
    capabilities: SourceCapabilities

class SourceCapabilities:
    passages: bool
    passage_sets: bool
    figures: bool
    option_images: bool
    rich_text: bool
    answer_explanations: bool
    sections: bool
    marks: bool

class SourceProvider(Protocol):
    def profile(self) -> SourceProfile: ...
    async def probe(self, scope: Scope) -> Coverage: ...
    async def fetch(self, scope: Scope) -> AsyncIterator[SourceItem]: ...
    def adapt(self, item: SourceItem, catalog: CatalogSnapshot) -> RawBundle: ...
    def validate(self, item: SourceItem) -> list[Issue]: ...
```

`SourceItem` keeps the raw payload, provenance and source-specific metadata. `adapt` maps it to the production scope and returns a `RawBundle` with stem, options, answer, passage, media, marks and warnings. The adapter does not tag, explain or verify.

`myschool` is one source provider with an exam scope. JAMB, WAEC and NECO are not three providers; they are three scopes of the same source. A second source, such as an official PDF archive or another portal, implements the same contract without touching the core. That is the proof that the plugin boundary works.

Contract tests:

- Recorded fixtures for list, detail, passage, figure, no-figure, missing-answer and malformed-option pages.
- A live smoke test with a small limit, run manually or nightly, not on every unit run.
- A `probe` test that checks counts and pagination.
- A `map_scope` test for every subject in the source map.
- An `adapt` test that asserts provenance, passages, marks and media.

### 9.3 AI contract

`complete(prompt) -> str` is too thin. A provider needs a profile and typed capabilities:

```python
class ModelProfile:
    provider: str
    model: str
    modalities: set[str]            # text, image
    context_tokens: int
    structured_output: bool
    cost_per_1k_input: float
    cost_per_1k_output: float
    rate_limit: RateLimit
    data_policy: str

class ModelProvider(Protocol):
    def profile(self) -> ModelProfile: ...
    def supports(self, capability: Capability) -> bool: ...
    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...
    async def structured(self, request: CompletionRequest, schema: type[T]) -> T: ...
```

Capabilities are narrow: `tag`, `explain`, `verify_answer`, `describe_image`, `extract_marks`. A provider may support one and not another. The router chooses a qualified provider by task, subject, modality, cost and scorecard. It does not use a hardcoded fallback list.

The model never writes. It returns a proposal with evidence and confidence. The core validates the proposal against the source and the catalog, then writes or rejects it. This is the same discipline as an agent calling a tool: the model chooses, the tool executes and validates. Here we define the tools and their contracts.

### 9.4 Catalog and tagging

The production catalog is the only source of exams, subjects, topics and subtopics. The run takes a catalog snapshot and records its version or hash on every bundle.

Tagging is a constrained choice, not free text. The prompt receives a pruned list of candidate topics and subtopics for the subject, with names and slugs. The output must name a slug from that exact list. The task validates the slug against the snapshot before writing. A tag without a valid subtopic is a failure, not a warning.

The tag proposal includes evidence: the part of the stem or passage that supports the classification. The core can reject a tag whose evidence is absent. This is how the model is held to the catalog rather than trusted to know it.

### 9.5 Media and RichText

Media is evidence, not a URL field. The bundle carries:

- `asset_id`, `content_hash`, `mime`, `width`, `height`, `storage_url`
- `source_url`, `fetched_at`
- `description` from a vision provider, with confidence and quoted visual facts
- `required` flag, set by the gate when the stem references a figure
- `readable` flag, set by the media/vision stage

If a figure is required and the asset is missing or unreadable, the bundle is not promotable. The question is not tagged on a guess. This is the user's point about image questions: without the image, the question is useless.

Rich text is one normalizer for every source and every text field. It maps `<u>`, `<b>`, `<i>`, `<s>`, `<sub>`, `<sup>` and `<img>` to marks, preserves `\n\n` for passages, measures Unicode characters, rejects marks past the text, rejects partial overlaps, and keeps text plain. It must produce the exact shape the Rust model validates. Add a fixture corpus with expected marks and hashes.

### 9.6 Review and trust policy

The reviewer is a provider. It can be a human CLI or an agent surface. It lists bundles, shows the evidence, records a decision and writes a verification. The credential decides what the decision may count as.

The trust policy is explicit and versioned:

- `human_v1`: the latest human pass over answer, explanation, passage and media when applicable. This is the only policy that sets `verified` under the current API.
- `ai_shadow`: AI passes are recorded as signal and compared with human decisions, but never set `verified`.
- `ai_v1`: a future policy that may set a new AI trust tier after per-task precision is measured and the API contract is changed. It must not write `kind='human'`.

Do not fake a human row to make the API green. That is the integrity line in D45 and D62. If the goal is zero human review, change the contract deliberately: add an `ai_verified` flag or a trust tier, and measure its precision. The current `verified` bool means a human checked it.

### 9.7 Evaluation harness

A provider is not production-ready because its unit tests pass. It is ready when its scorecard says so.

The harness needs:

- Gold sets per task: tagging, answer verification, explanation, image description, mark extraction.
- Stratification by exam, subject, section, question type, has-image, has-passage and language.
- Metrics: exact match, macro F1, precision, recall, calibration, abstention rate, cost per 1k and p95 latency.
- A held-out split, not the rows used to tune the prompt.
- A versioned prompt and schema. A change reruns the eval.
- A scorecard stored with provider, model, prompt version, dataset hash, metrics and date.
- A `qualify` command that writes the scorecard. The pipeline checks it before auto-promotion.
- A shadow mode for a new provider. Run it on production samples, compare with the current provider or human verdict, and do not promote.
- A nightly or weekly live smoke on a small real paper, with a cost cap.

The top metric is not average confidence. It is precision on auto-promoted rows at a stated coverage. A system that auto-promotes 40 percent of rows at 99 percent precision is better than one that auto-promotes 90 percent at 85 percent precision. The remaining 60 percent can wait for review.

### 9.8 Acceptance and promotion

Promotion is a transaction over the bundle:

1. Load the bundle and its latest trusted verification.
2. Recompute the bundle hash from the stored content, passage and media evidence.
3. Check the hash matches the verification.
4. Check the subtopic exists in the catalog snapshot.
5. Check the passage and media rows exist.
6. Check the policy allows the verification kind.
7. Write the question, passage, media link and verification in one transaction.
8. Apply the exact production predicate to the written row.
9. Record the promotion and the predicate result.

If step 8 fails, the promotion fails and the bundle stays out of ready. The predicate is the acceptance test, not a postmortem.

## 10. Keep or rewrite

**Recommendation:** do not start a new project from zero. Refactor the bank into the provider core and treat the pipeline as a donor. Replace the spine, keep the organs. If the current `task/` layer keeps fighting the provider model, extract a new `core` package inside the same repository and port the bank's gate, reference, media and contract modules into it. That is a rewrite of the spine, not a rewrite of the product.

**Why not a full rewrite now:**

- The bank already has the hard domain knowledge: gate rules, content hash, RichText contract, reference reader, lanes, media tasks and production checks.
- The pipeline does not have a better architecture; it has a better scraper and a good prompt. It has the same fatal seam.
- A new project would spend its first weeks rebuilding the gate and contract tests, then risk the same bundle split.
- The user wants coverage. A rewrite that does not fix the seam does not buy coverage.

**When a new package is justified:** if the bank's task registry and lane assumptions prevent a clean provider boundary, create `utmelab_bank/core` with the bundle, ports and sequence, and keep the old modules as adapters until parity. Do not create a fourth top-level Python tree. One factory, one CLI, one contract test.

**What to do with the pipeline:** port its source detail scraper, passage extraction, OpenCode stdin/vision pattern, bounded concurrency, metrics and dry-run sync. Then archive it or keep it read-only. Two factories will drift again.

## 11. Execution plan

### Step 0. Decide the trust contract

Answer the question in section 12 before writing code. The rest of the design depends on whether `verified` stays human-only or gains an AI tier.

### Step 1. Write `SPEC.md`

One page. Include the bundle, the provider ports, the trust policy, the acceptance predicate and the non-goals. Do not write a long design document. The spec is the agreement the tests enforce.

### Step 2. Make the first test fail

One end-to-end test with:

- A fake source that returns a paper with a comprehension passage, a data-block question, a figure whose image is in the HTML, a duplicate image, an ad image and a wrong answer key.
- A fake catalog with a known topic and subtopic.
- A fake model that returns a tag with a wrong underline offset, an explanation, and an answer check that is wrong for one row.
- A temporary database.

Run the real sequence and apply the exact production predicate. Assert:

1. The promoted comprehension row has its passage and verification in the target lane.
2. The production predicate returns true for every row promotion reports as ready.
3. The wrong-key row cannot promote until a trusted verification is written.
4. The no-passage row cannot promote.
5. The figure appears once and the ad image is absent.
6. The underline is snapped or dropped.
7. A gate failure never reaches ready.
8. A human fail blocks promotion.
9. The subtopic exists in the catalog snapshot.

This test must fail on both current systems. That is the point.

### Step 3. Fix the spine

In order:

1. Bundle model and bundle hash.
2. Atomic promotion that copies the deciding verification.
3. `assert_promotable` with gate, explanation, subtopic, passage, media and verification.
4. Review CLI with show, next, set, verify, stats and fail.
5. Latest-human semantics in one helper.
6. Workflow that promotes and checks the predicate.

Do not add sources or AI tasks until this test passes.

### Step 4. Run one real paper

Pick one JAMB paper. Run it from source to ready. Inspect the ready rows with the production predicate. Check the passage, figures and underlines by eye. This catches source and model behavior that fakes cannot.

### Step 5. Build the evaluation harness

Create a starter gold set. Start with the paper from Step 4 and a sample from production. Measure the tagger, answer verifier and explainer separately. Store scorecards. Do not enable auto-promotion yet.

### Step 6. Make the source plugin real

Refactor `myschool` into one provider with an exam scope. Add `probe`, `adapt`, `validate`, `profile` and contract fixtures. Then add a second source, even a small one, to prove the boundary. The second source should not require changes to the core.

### Step 7. Add media evidence

Fetch, hash and store figures. Describe them with a vision provider. Gate on reachability. Require a description for image-dependent rows. Link the asset to the bundle and include it in the hash.

### Step 8. Add policy and shadow mode

Run AI verification in shadow against human decisions. Measure precision and calibration. When a task meets the threshold, allow it to auto-advance to a candidate queue. Only change `verified` if the API contract is deliberately extended.

### Step 9. Then expand

Add probe, duplicate audit, underline worksheet, passage recovery and bounded concurrency. These improve throughput and repair, but none fixes the seam. Do them after the spine is green.

### Step 10. Archive the duplicate factory

After parity, archive `utmelab-pipeline` or keep it read-only. One factory, one source registry, one AI registry, one acceptance test.

## 12. Questions for the user

These decisions change the implementation. They should be answered before the spec is frozen.

1. **Trust contract.** Should `verified` stay human-only for now, with AI producing a candidate tier, or should we add an explicit AI trust tier to the API? My recommendation is human-only now, and a measured AI tier later. It is the only way to keep the meaning of `verified` honest.
2. **One factory.** Should the bank become the single factory and absorb the pipeline, or should we start a new package with the bank and pipeline as donors? My recommendation is the bank as the base, with a new spine if needed.
3. **Pipeline fate.** Archive `utmelab-pipeline` after parity, or keep it as a reference implementation? Two factories will drift.
4. **First paper.** JAMB English stresses passages, underlines and comprehension. JAMB Physics stresses figures, formulas and vision. Which one should be the first real end-to-end paper? I would start with English because the passage seam is the largest coverage gap, then Physics for vision.
5. **Gold set.** Can you provide or approve a small human-verified gold set for the first paper and a production sample? Without labels, "accuracy" cannot be measured, and auto-promotion cannot be justified.

## 13. Evidence index

**Bank acquisition and parsing**

- `src/utmelab_bank/source/myschool/parser.py`: API and HTML parsing, figure marks, passage extraction, ad filtering.
- `src/utmelab_bank/source/myschool/run.py`: API and HTML fetch loops, page defaults.
- `src/utmelab_bank/fill.py`: strategy selection, dry run, page count.
- `src/utmelab_bank/rules.py`: gate rules, passage presence, option counts.
- `tests/fixtures/myschool_physics_page1.json`: captured API row keys, no passage field.

**Bank lifecycle**

- `src/utmelab_bank/task/promote.py`: promotion conditions, passage copy, no verification copy.
- `src/utmelab_bank/task/ai/verify.py`: `ai_verify` writes.
- `src/utmelab_bank/task/ai/tag.py`: subtopic write, underline discarded.
- `src/utmelab_bank/task/review/verify.py`: verification scope and latest-row bug.
- `src/utmelab_bank/task/review/set.py`: scalar edits, no explanation edit.
- `src/utmelab_bank/task/__init__.py`: task registry, no review task.
- `src/utmelab_bank/store/selectors.py`: `unverified` selector, no `no-passage` selector.
- `tests/test_intake.py`: chain test, promotion success only.
- `.github/workflows/bank-ingest.yml`: ingest stops at dedupe.
- `.github/workflows/bank-enrich.yml`: enrich stops at AI verify.
- `README.md`: documented lifecycle, review stage, promotion stage.
- `ROADMAP.md`: known passage hash gap.

**Pipeline**

- `utmelab-pipeline/pipeline/orchestrator/promoter.py`: approved verification kind and scope.
- `utmelab-pipeline/pipeline/orchestrator/sync_prod.py`: production sync without verification writes.
- `utmelab-pipeline/pipeline/orchestrator/worker.py`: auto-approval threshold and promotion.
- `utmelab-pipeline/pipeline/storage/repository.py`: staging dedupe, auto status, production syllabus read.
- `utmelab-pipeline/pipeline/sources/base.py`: `RawQuestionPayload`, `BaseHarvester`.
- `utmelab-pipeline/pipeline/sources/jamb.py`, `waec.py`, `neco.py`: duplicated myschool scrapers.
- `utmelab-pipeline/pipeline/sources/__init__.py`: hardcoded source registry.
- `utmelab-pipeline/pipeline/ai/runner.py`: hardcoded model candidates.
- `utmelab-pipeline/pipeline/ai/tasks.py`: underline only, no RichText mapping.
- `utmelab-pipeline/pipeline/ai/prompts.py`: one combined prompt, no catalog validation.
- `utmelab-pipeline/pipeline/gates/mechanical.py`: Gate 0.
- `utmelab-pipeline/pipeline/gates/media_check.py`: unused reachability check.
- `utmelab-pipeline/pipeline/cli.py`: review list only, manual stage commands.
- `utmelab-pipeline/tests/test_sync_prod.py`: no production verification assertion.
- `.github/workflows/pipeline.yml`: single manual job, no end-to-end run.
- `utmelab-pipeline/docs/ROADMAP_AND_MILESTONES.md`: unsupported production-ready claim.

**Production contract**

- `src/store/catalog.rs`: `verified_predicate`, `LATEST_VERIFIED_CTE`, latest-human rule.

**Old decisions**

- `utmelab-api-old/docs/QUESTION_BANK_DECISIONS.md`: D16, D45, D50, D60, D61, D62, D64.
- `utmelab-api-old/docs/HANDOFF.md`: lifecycle rules and traps.
- `utmelab-api-old/docs/REVIEW_METHOD.md`: review discipline.
- `utmelab-api-old/docs/UNDERLINE_PROBLEM.md`: underline history.
- `docs/NOTES.temp.md`: current shape, pipeline ownership, no in-process bank writes.

**Tools**

- `tools/harvest.py`: detail fetch, passage extraction, figure dedupe, ad filter.
- `tools/harvest_all.py`: bulk probe and resume.
- `tools/recover_passages.py`: passage backfill.
- `tools/review.py`: review CLI and correct latest-human rule.
- `tools/dup_audit.py`: duplicate audit and strict exit.
- `tools/drop_rows.py`: curated drop with twin guard.
- `tools/propose_emphasis.py`: underline worksheet.
- `tools/write_recovered_explanations.py`: curated explanations.
- `tools/auto_verify_opencode.py`: legacy auto-accept, not a target.
- `tools/auto_tag_questions.py`, `tools/utmetag/runner.py`: bulk tagging, underline output, concurrency.
- `tools/import_syllabus.py`: removed, production catalog replaces it.
