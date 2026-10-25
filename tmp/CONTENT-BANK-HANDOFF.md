# Content-bank handoff

Date: 2026-10-25

## Current state

The bank Turso database is reachable when the agent uses external network
access. A read-only query succeeded against the configured bank database. It
contains 3,450 staging rows, including 82 rows with media.

The earlier DNS failure was sandbox isolation, not a Turso outage.

## Completed in this run

- Replaced the detached 14-case media benchmark with 17 cases based on current
  bank staging rows and two malformed media fixtures.
- Added source item ID, exam, subject, year, answer option, and catalog
  placement where the bank row exposes them.
- Downloaded and visually checked the current benchmark images from the media
  repository.
- Fixed the local media benchmark runner to accept both `.png` and `.jpg` files
  and to derive MIME from the stored extension.
- Re-ran the deterministic benchmark: 17 cases, 0 failures.
- Added `scripts/run_ocr_benchmark.py` for one bounded OCR pass over the current
  manifest.
- Ran the bounded OCR pass against the current media set and fixed the scorer
  to match both `.jpg` and `.png` result filenames by asset hash.

## Important evidence boundary

The current benchmark source rows are real bank rows. Most current rows do not
have catalog placement yet, so catalog fields remain null where the DB returned
null. No catalog, answer, or explanation was invented.

The full content cases remain `verified: false` until the source question,
catalogue placement, canonical answer, and explanation requirements are checked
together.

## Validation before handoff

- Ruff passed.
- Mypy passed.
- Benchmark manifest contract test passed.
- Deterministic current-media benchmark passed: 17/17.
- OCR.space current-bank baseline: 7/17 cases met every required text fragment.
  Ten failures are retained as genuine OCR misses involving small labels, map
  text, diagram symbols, and numeric annotations.
- READY now rejects explanations that do not identify or support the canonical
  answer. The deterministic check accepts the answer option ID, option text,
  or a simple numeric word equivalent.
- The restricted sandbox appeared to hang at the thread-backed database test.
  The same database tests pass outside the sandbox, and the complete non-live
  suite passes there: 413 passed, 13 deselected. This was an execution
  environment limitation, not a Turso adapter failure.
- The explanation provider prompt now requires distractor reasoning,
  calculation steps, unit preservation, trusted figure evidence, and explicit
  uncertainty instead of invented values or relationships.
- Tag proposals below 0.60 confidence now abstain before catalog placement and
  remain available for review.
- Passing answer reviews below 0.70 confidence now become abstentions and are
  rejected from VERIFIED instead of moving forward as trusted checks.
- Explanation and answer-review providers now receive persisted OCR records and
  deterministic media checks alongside image descriptions.
- READY explanations must now address every distractor as well as support the
  canonical answer.
- Provider selection is now contract-tested: mock and OpenCode are selected
  explicitly, and unknown names fail without fallback.

## Next exact action

Run or repeat the bounded OCR pass with external network access from
`utmelab-bank`:

```bash
python scripts/run_ocr_benchmark.py --media-root /path/to/current/media > /tmp/current-ocr.json
python scripts/score_ocr_benchmark.py /tmp/current-ocr.json
```

Use the current GitLab media repository or the local media store as the media
root. Keep the provider result outside Git, inspect failures by case, and do
not launch a batch. The current result is in `/tmp/utmelab-current-ocr-score2.json`
for this machine only.

After OCR scoring:

1. Correct only benchmark labels proven wrong by the image.
2. Add catalog snapshots for rows whose production placement is available.
3. Add explanation checks for answer agreement, distractors, units, and figure
   claims.
4. Run the full non-live suite.
5. Update this handoff and the roadmap, then commit and push.

The focused explanation and tagging pipeline tests pass, and the complete
non-live suite also passes outside the restricted sandbox: 408 passed, 13
deselected.

## Recent commits

- `fb91502` blocks non-OK media checks from READY.
- `41ca3b1` records the quality checkpoints in the roadmap.
- `a164743` allows normalized trusted OCR evidence for tagging.
- `48afb5e` tightens the image-description evidence prompt.
- `2e26c35` persists and scores media evidence.
