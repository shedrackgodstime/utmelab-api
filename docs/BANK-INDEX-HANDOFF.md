# Bank index handoff

This is a handoff for the `utmelab-bank` owner. The Rust API does not create or
migrate indexes on bank-owned tables.

The live query-plan review found three possible pipeline-side improvements:

- Question pages use the `(exam, subject)` index and then sort by `id`. Test an
  `(exam, subject, id)` index against the real bank.
- Latest verification lookup still scans and sorts the verification window.
  Test a wider index that matches its filter and ordering.
- Subject discovery still sorts while grouping. Measure whether an index helps
  before adding one.

For each candidate, compare `EXPLAIN QUERY PLAN`, latency, write cost, and index
size on the real bank. Add accepted indexes in the bank pipeline and rerun the
API benchmark afterward. No Rust API change is required for this handoff.
