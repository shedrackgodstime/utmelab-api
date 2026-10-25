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
- The OCR provider pass was not started successfully in the final step because
  the command process could not be created in the restricted tool session. No
  OCR result should be inferred from that failed attempt.

## Next exact action

Run the bounded OCR pass with external network access from `utmelab-bank`:

```bash
python scripts/run_ocr_benchmark.py --media-root /path/to/current/media > /tmp/current-ocr.json
python scripts/score_ocr_benchmark.py /tmp/current-ocr.json
```

Use the current GitLab media repository or the local media store as the media
root. Keep the provider result outside Git, inspect failures by case, and do
not launch a batch.

After OCR scoring:

1. Correct only benchmark labels proven wrong by the image.
2. Add catalog snapshots for rows whose production placement is available.
3. Add explanation checks for answer agreement, distractors, units, and figure
   claims.
4. Run the full non-live suite.
5. Update this handoff and the roadmap, then commit and push.

## Recent commits

- `fb91502` blocks non-OK media checks from READY.
- `41ca3b1` records the quality checkpoints in the roadmap.
- `a164743` allows normalized trusted OCR evidence for tagging.
- `48afb5e` tightens the image-description evidence prompt.
- `2e26c35` persists and scores media evidence.
