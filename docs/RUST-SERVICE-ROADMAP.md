# Rust Service Roadmap

This roadmap covers the Rust API only. The site placeholder and
`utmelab-bank` are out of scope.

The service must remain safe when the remote content database is large, the
VPS has limited CPU and RAM, and traffic is higher than the measured capacity.
Content belongs in SQLite. RAM is for the current request and its bounded
result.

## Current baseline

- Local `db/sync.db` is the serving replica.
- Full question bodies are fetched only after paper selection.
- Paper candidate selection streams database rows and keeps a bounded
  reservoir.
- Novel question pages use SQL `COUNT(*)`, `LIMIT`, and `OFFSET`.
- Public novel detail does not load quiz content.
- Rate-limit buckets have a hard memory cap.
- Question sampling uses bounded-memory reservoir sampling.
- Novel listing is SQL-paged with a bounded response.
- Passage batch requests reject more than 100 IDs instead of silently
  truncating the result.
- Passage catalog listing has a separate SQL-paged route:
  `/api/v1/passages/catalog/{exam}/{subject}`.
- Novel detail loading never reads quiz rows; quiz access is isolated to the
  SQL-paged questions endpoint.
- Question text search is capped at 256 characters before it reaches SQLite.
- Regression tests cover SQL page windows and a 100,000-row candidate stream
  whose paper reservoir remains fixed at 50 rows.
- Paper candidate verification uses the set-based latest-verification CTE,
  avoiding a correlated verification calculation for every streamed row.
- Paper assembly, scoring, and question sampling have a separate per-key
  expensive-operation ceiling of 20 requests per minute.
- The sync supervisor retries pending local pushes before pulling, and records
  sync failures and the latest pull duration on the admin status surface.
- Sync polling sleeps after five minutes without traffic. The first database
  request wakes it with one locked pull before serving.
- Active synchronization uses Turso long-polling. There is no interval-pull
  mode or legacy polling configuration.
- Long-poll duration is bounded to 1-5 seconds by configuration, and admin
  status records write waits caused by sync serialization.
- Public discovery metadata is cached in a bounded in-process tree keyed by
  bank version. It does not cache question content, and sync revisions cause
  automatic recalculation.
- Formatting, Clippy, and the Rust test suite pass.

## Batches

### Batch 1: bounded reads

Status: complete.

1. Done. Audited remaining metadata responses for explicit size bounds.
2. Done. JSON bodies are capped at 16 KiB, metadata row dumps at 100 rows,
   pages at 200 rows, passage batches at 100 IDs, and question search at 256
   characters.
3. Done. Every batch endpoint has a hard item limit and every page endpoint
   clamps both page size and offset safely.
4. Done. Route tests cover the bounded response paths. Live smoke tests remain
   part of each future batch.

### Batch 2: large-bank correctness

Status: mostly complete.

1. Add synthetic large-bank tests for streamed candidate selection.
2. Prove paper selection memory stays bounded by paper size, not bank size.
3. Benchmark paper assembly, scoring, sampling, and pagination with large
   subjects.
4. Test very large page numbers, empty results, and short pools.
5. Done. `scripts/live-benchmark.sh` reports live latency, status, and response
   size without changing Turso data. Server memory sampling remains an
   operational load-test task.

### Batch 3: database speed

Status: query-plan audit complete. Rust-side optimization next.

Measured Turso plans on 2026-11-07:

- The question page uses `idx_q_exam_subject (exam, subject)`, then sorts by
  `id` for the page window. A bank-owned `(exam, subject, id)` index is the
  measured candidate for removing that sort.
- Verification lookup uses `idx_ver_q (question_id, created_at)` for a known
  question, but the latest-verification window still scans and sorts the human
  verification rows. A wider index must be tested against the real bank before
  it is added.
- Subject discovery uses the subject primary-key index and the question exam
  and subject index. It still sorts for grouping, so the current bounded
  metadata cache remains useful.
- The API will not create indexes on bank-owned tables. Index changes belong in
  the content pipeline, followed by another live plan and latency measurement.

1. Done. Inspect Turso query plans for questions, verifications, subjects, and
   country scope.
2. Hand measured bank-index changes to the pipeline owner. Do not create bank
   indexes from the API.
3. In progress. Paper candidate verification is now restricted to the requested
   exam and subject before ranking. A ten-run live comparison reduced paper
   assembly from a median of about 0.81s to about 0.54s.
4. Done. Paper assembly now uses a one-entry, bank-version-keyed metadata
   cache for exam, subject, blueprint, and syllabus metadata. Question content
   and candidate rows remain uncached. Live warm requests were about 0.52–0.57s
   after a cold request of about 0.94s.
5. Keep database work streamed even when the result is small.
6. Re-run live plans and latency measurements after each index or query change.

### Batch 4: traffic protection

Status: baseline load-tested. Broader resource profiling remains.

1. Done. Route-specific limits exist for paper assembly, sampling, and text
   search.
2. Done. Expensive requests fail fast when the database gate is full.
3. Done for the first live profile. One hundred concurrent public requests and
   fifty concurrent keyed question requests returned `200`. A sustained debug
   profile held at about 4.1 MiB RSS, with CPU below 7% after startup.
4. Done for expensive traffic. Twenty-five concurrent paper requests produced
   both successful responses and `429` shedding, with no unbounded queue.
5. Keep admin limits bounded in production configuration.
6. Add a small load profile for public discovery, keyed reads, paper assembly,
   and sync activity.

### Batch 5: write and sync safety

1. Done. Writes commit locally under the write mutex, surface push failure, and
   the sync supervisor retries pending pushes before pulling.
2. Done. Reports use conflict-safe inserts. Key creation and rotation remain
   non-idempotent by design, so an unknown result must not be blindly retried.
3. Done. Failed pulls and pushes retry after short backoff while the last safe
   replica remains available.
4. Done. Admin status exposes engine WAL sizes, freshness, pull duration, and
   sync failure counters.
5. Done. Contract checks fail closed for data routes when the replica shape is
   incompatible.

### Batch 6: security and cleanup

1. Done. Authentication, scopes, admin boundaries, and public route inventory
   were rechecked after the read changes.
2. Done. Remaining `unwrap`, `expect`, and panic calls are test-only, except
   for no production panic path. Migration fallback now returns an error.
3. Done. Public discovery routes expose metadata only. Keyed question routes
   retain answer and explanation access according to their existing contract.
4. Done. Obsolete unbounded catalog readers are test-only and cannot enter the
   production build.
5. Done. Format, Clippy, tests, and the checked-in OpenAPI contract pass.

### Batch 7: operational readiness

Status: in progress.

1. In progress. Live no-database startup returns health `200`, readiness `503`,
   and data-route `503` while the process remains healthy.
2. Confirm logs never contain API keys, passwords, session tokens, or database
   tokens.
3. Check admin metrics for freshness, pull duration, write wait, failures, and
   request latency.
4. Confirm graceful shutdown does not leave a local write or pending push
   unaccounted for.
5. Document the production rollback and replica-rebuild procedure.

### Batch 8: release validation

Status: pending.

1. Run the complete Rust test, format, Clippy, and OpenAPI checks from a clean
   checkout.
2. Run live smoke tests against a read-only production-like database.
3. Verify public, keyed, admin, and MCP route boundaries.
4. Record baseline latency and response sizes for the main endpoints.
5. Review every changed file for stale code, accidental secrets, and unrelated
   scope before release.

### Batch 9: security stress validation

Status: started after implementation batches.

1. Done. Missing and invalid API keys return `401`.
2. Done. Malformed JSON returns `400`, and oversized request bodies return
   `413`.
3. Done. A 100-request public flood completed without a process failure.
4. Done for keyed floods and database-gate saturation. A 30-request test with
   one DB permit returned one `200` and twenty-nine fast `503` responses. Slow
   clients remain an open finding: a 10-bytes-per-second upload held the body
   path beyond 15 seconds, so the current handler timeout is not a total upload
   deadline.
5. Observe CPU, RSS, open connections, latency, status distribution, sync
   failures, and replica freshness during each test.
6. Stop every test cleanly and confirm the service returns to its baseline.

The local host has substantially more than the target shared-VPS memory, so
the observed RSS is a baseline only. It does not prove behavior under a 2 GB
host limit.

## Working rule

Every new endpoint or query must answer these questions before it is merged:

- Can its memory use grow with database size?
- Is the result bounded in SQL?
- Does it load content before knowing it is needed?
- What happens when the database gate is saturated?
- Does the response reveal data that the route should withhold?
- Is the behavior covered by a large-bank test?

## Definition of done

The Rust service is ready for a large bank when database size increases query
work but does not increase request memory without an explicit bound, expensive
requests shed load predictably, writes recover safely, and the complete test
and measurement suite proves those properties.
