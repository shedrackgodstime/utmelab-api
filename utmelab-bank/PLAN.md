# Bank work queue

One queue, newest facts first. Finished items leave the list. The bank facts
below were measured on 2026-10-26 from the bank and production databases.

## Bank state

| State | Rows | Note |
|---|---|---|
| deduped | 3054 | 2261 NECO, 793 WAEC |
| catalogued | 182 | all WAEC |
| ready | 90 | |
| rejected | 172 | |

Of the 3054 deduped rows: 747 are taggable (WAEC), 2261 are NECO with no
production catalog, 49 are WAEC agricultural-science where production holds
two topics with blank names.

## Now

1. **Catalog: blank topic names.** `ProductionCatalogReader` crashes with a
   pydantic `ValidationError` when a topic name is empty (WAEC
   agricultural-science, topics `waec-agricultural-science-50-` and `-51-`,
   13 subtopics under them). Skip the unusable topic and log the defect, so
   the rest of the subject is usable and the data problem stays visible.
2. **Limits, not reports.** When every route fails with a retryable error the
   run must stop, not re-attempt three providers for every remaining row.
   Add provider exhaustion to the failover wrapper and a consecutive-failure
   cap to every batch task, and stop the preset when a task stops.

## Next

3. **Process the WAEC runway.** 747 taggable deduped rows through
   `tag -> media -> explain -> review -> ready` in batches of about 200.
   Tagging alone is roughly 20s per row on the opencode route. The free
   quota is expected to run out; failover covers it until every route is
   exhausted, at which point item 2 stops the batch.

## Parked

- **NECO.** 2261 deduped rows cannot be tagged. Production has 36 NECO
  subjects and zero NECO topics and subtopics. The bank never writes
  production (decision D8), so this needs a catalog seeded outside the bank.
  Parked by decision.

## Tools

- **Separate read-only database CLI.** `utmelab-db` is its own command, not
  part of the pipeline CLI. It reads `.env` through `load_settings`, so no
  token is ever passed on a command line or pasted into a terminal. Complex
  work imports `utmelab_bank.db` instead of writing a Turso connection.
