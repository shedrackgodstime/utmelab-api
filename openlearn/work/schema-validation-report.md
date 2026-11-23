# Schema v0.1 validation report

Status: validation of the three pilots against `openlearn/conventions/schema-v0.1.json`. No records changed.

Validation method: each record is validated against its `kind` definition directly (the root `oneOf` is for mixed documents; per-record validation gives clearer errors).

## Summary

| Pilot | Records | Pass | Fail |
|---|---:|---:|---:|
| pilot-001-newton | 8 | 6 | 2 |
| pilot-002-economics | 16 | 7 | 9 |
| pilot-003-math-proof | 13 | 5 | 8 |

## pilot-001-newton

**Pass (6):** `external-placement.json`, `source-attribution.json`, `source-fidelity.json`, `statement-newtons-second-law.json`, `statement-related-to-first-law.json`, `study-topic-section.json`

**Fail:**

- `concept-newtons-second-law.json`
  - <root>: 'definition_status' is a required property
  - <root>: {'id': 'concept:newtons-second-law', 'kind': 'Concept', 'label': 'Newton’s Second Law of Motion', 'scope': {'text': 'Newtonian/classical mechanics (introductory)', 'basis': 'inferred'}, 'linked_statements': ['statement:newtons-second-law', 'statement:newtons-second-law-related-to-first-law'], 'notes': 'Named law as a Concept anchor per convention (a); the law’s content is carried by linked Statements. Scope conditions (inertial frame, non-relativistic speeds) are not stated in the captured blocks and remain inferred/unresolved.', 'source_refs': ['source:openstax-m42073']} is not valid under any of the given schemas
- `relation-related-to-first-law.json`
  - direction: 'symmetric-or-unspecified' is not one of ['directed', 'symmetric', 'unspecified']

## pilot-002-economics

**Pass (7):** `external-placement.json`, `source-attribution.json`, `source-fidelity.json`, `statement-above-equilibrium-surplus.json`, `statement-below-equilibrium-shortage.json`, `statement-equilibrium-condition.json`, `study-topic-section.json`

**Fail:**

- `concept-demand.json`
  - <root>: 'definition_status' is a required property
  - <root>: Additional properties are not allowed ('definition_fidelity' was unexpected)
- `concept-equilibrium.json`
  - <root>: 'definition_status' is a required property
  - <root>: Additional properties are not allowed ('definition_fidelity' was unexpected)
- `concept-quantity-demanded.json`
  - <root>: 'definition_status' is a required property
  - <root>: Additional properties are not allowed ('definition_fidelity' was unexpected)
- `concept-quantity-supplied.json`
  - <root>: 'definition_status' is a required property
  - <root>: Additional properties are not allowed ('definition_fidelity' was unexpected)
- `concept-supply.json`
  - <root>: 'definition_status' is a required property
  - <root>: Additional properties are not allowed ('definition_fidelity' was unexpected)
- `model-demand-supply-equilibrium.json`
  - assumptions/0/basis: 'as-stated (ceteris paribus) / inferred (single-market framing)' is not one of ['stated', 'inferred', 'mixed', 'not_extractable']
  - assumptions/1/basis: 'as-stated' is not one of ['stated', 'inferred', 'mixed', 'not_extractable']
  - assumptions/2/basis: 'as-stated/inferred from adjustment narrative' is not one of ['stated', 'inferred', 'mixed', 'not_extractable']
- `procedure-locate-equilibrium.json`
  - source_fidelity: 'as-stated/condensed' is not one of ['as-stated', 'paraphrased', 'verified', 'corrected', 'not-extractable']
- `statement-law-of-demand.json`
  - scope/basis: 'as-stated for ceteris paribus; broader scope inferred' is not one of ['stated', 'inferred', 'mixed', 'not_extractable']
- `statement-law-of-supply.json`
  - scope/basis: 'as-stated for ceteris paribus; broader scope inferred' is not one of ['stated', 'inferred', 'mixed', 'not_extractable']

## pilot-003-math-proof

**Pass (5):** `external-placement.json`, `source-attribution.json`, `study-proof-ftc-part1.json`, `study-proof-ftc-part2.json`, `study-topic-section.json`

**Fail:**

- `concept-antiderivative.json`
  - <root>: 'definition_status' is a required property
  - <root>: Additional properties are not allowed ('definition_fidelity' was unexpected)
- `concept-definite-integral.json`
  - <root>: 'definition_status' is a required property
  - <root>: Additional properties are not allowed ('definition_fidelity' was unexpected)
- `concept-fundamental-theorem-of-calculus.json`
  - <root>: 'definition_status' is a required property
  - <root>: Additional properties are not allowed ('definition_fidelity' was unexpected)
  - scope/basis: 'as-stated for continuity conditions; broader calculus scope inferred' is not one of ['stated', 'inferred', 'mixed', 'not_extractable']
- `procedure-prove-ftc-part1.json`
  - scope/basis: 'as-stated' is not one of ['stated', 'inferred', 'mixed', 'not_extractable']
  - source_fidelity: 'as-stated/condensed' is not one of ['as-stated', 'paraphrased', 'verified', 'corrected', 'not-extractable']
- `procedure-prove-ftc-part2.json`
  - scope/basis: 'as-stated' is not one of ['stated', 'inferred', 'mixed', 'not_extractable']
  - source_fidelity: 'as-stated/condensed' is not one of ['as-stated', 'paraphrased', 'verified', 'corrected', 'not-extractable']
- `source-fidelity.json`
  - items/1/fidelity: 'not extractable from this capture' is not one of ['as-stated', 'paraphrased', 'verified', 'corrected', 'not-extractable']
  - items/2/fidelity: 'not extractable from this capture' is not one of ['as-stated', 'paraphrased', 'verified', 'corrected', 'not-extractable']
  - items/5/fidelity: 'as-stated/condensed' is not one of ['as-stated', 'paraphrased', 'verified', 'corrected', 'not-extractable']
  - items/6/fidelity: 'as-stated/condensed' is not one of ['as-stated', 'paraphrased', 'verified', 'corrected', 'not-extractable']
  - items/7/fidelity: 'as-stated/condensed' is not one of ['as-stated', 'paraphrased', 'verified', 'corrected', 'not-extractable']
  - items/8/fidelity: 'as-stated/condensed' is not one of ['as-stated', 'paraphrased', 'verified', 'corrected', 'not-extractable']
- `statement-ftc-part1.json`
  - scope/basis: 'as-stated for continuity/definition; broader calculus scope inferred' is not one of ['stated', 'inferred', 'mixed', 'not_extractable']
  - status: 'derived/proved' is not one of ['definitional', 'descriptive', 'normative', 'derived', 'empirical', 'provisional', 'asserted']
- `statement-ftc-part2.json`
  - scope/basis: 'as-stated for continuity/antiderivative; broader calculus scope inferred' is not one of ['stated', 'inferred', 'mixed', 'not_extractable']
  - status: 'derived/proved' is not one of ['definitional', 'descriptive', 'normative', 'derived', 'empirical', 'provisional', 'asserted']

## Systemic mismatches and normalization map

| Issue | Seen in | v0.1 expectation | Normalization |
|---|---|---|---|
| Embedded `definition_fidelity` field | Pilot 002/003 concepts | Use `definition_status` (`complete|assumed|not_extractable|pending`) | Replace `definition_fidelity` with `definition_status`; map `as-stated`→`complete`, `not extractable from this capture`→`not_extractable`, `as-stated/condensed`→`complete` (note condensed in `notes`) |
| Missing `definition_status` / definition | Pilot 001 concept | Concept requires `definition_status` and one of `definition_refs`/`definition` | Add a definitional Statement ref or mark `definition_status: pending` and add a temporary definition |
| `basis` free text | Pilot 002/003 | Enum: `stated|inferred|mixed|not_extractable` | Map `as-stated`→`stated`; `as-stated ...; inferred ...`→`mixed`; `as-stated/inferred...`→`mixed` |
| `source_fidelity` free text | Pilot 002/003 | Enum: `as-stated|paraphrased|verified|corrected|not-extractable` | Map `as-stated/condensed`→`paraphrased`; `not extractable from this capture`→`not-extractable` |
| `status: derived/proved` | Pilot 003 | Enum includes `derived` | Use `status: derived` + `role: theorem` |
| `direction: symmetric-or-unspecified` | Pilot 001 relation | Enum: `directed|symmetric|unspecified` | Choose `unspecified` for the vague “closely related” relation (or make it specific) |
| ID pattern rejected underscores | External placement IDs | Pattern now allows `[a-z0-9_-]` | Fixed in v0.1 after first validation pass |

## Interpretation

- The schema is usable but stricter than the pilot records; failures are mostly vocabulary/normalization, not structural contradictions.
- The largest real gap is definition handling: Pilot 001 has a Concept with no definition Statement; Pilot 002/003 embed definitions with a non-schema `definition_fidelity` field.
- Proof representation held: theorem Statements, reusable proof Procedures, and specific Study derivations all validate once vocabulary is normalized.
- Model representation held: demand/supply validates once assumption `basis` values are normalized.

## Normalized re-validation

The pilots were normalized by `work/normalize-v0.1.py` into `work/normalized/pilot-00*/`. Originals under `work/pilot-00*/` are unchanged. Normalization applied the map above mechanically: enum vocabulary, `definition_fidelity` → `definition_status`, `derived/proved` → `derived` + `role: theorem`, and `direction: symmetric-or-unspecified` → `unspecified`.

Pilot 001's Concept anchor has no separate definitional Statement; it now points at `statement:newtons-second-law` via `definition_refs`, with a note that the named law is constituted by its Statement. This is an explicit pilot compromise, not the production rule.

Result from `python3 work/validate.py` (schema + cross-record checks over `work/normalized/`):

```
records: 37  pass: 37  fail: 0
errors: 0  warnings: 8
```

Warnings only:

- Six dangling refs in `pilot-001-newton`: `concept:newtons-first-law`, `concept:acceleration`, `concept:net-external-force`, `concept:mass`, `concept:system`. Expected: those Concepts are referenced but not extracted in the pilot.
- Two unvetted Concepts in `pilot-003-math-proof`: `concept:definite-integral`, `concept:antiderivative` (`definition_status: not_extractable`). Expected: the source assumes them from prior sections.

No schema failures, no duplicate IDs, no missing licenses, and no exam identifiers leaked into Knowledge/Study records.

## Validator

`work/validate.py` checks:

1. JSON parses and each record validates against its `kind` definition in `conventions/schema-v0.1.json`.
2. IDs are unique across the loaded set.
3. Reference fields resolve: `source_refs`, `definition_refs`, `linked_statements`, `distinguished_from`, `about`, `provenance`, `knowledge_refs`, `components`, `predictions`, `from`, `to`, `source_ref`, `supports_relation`, `items[].ref`.
4. Every `SourceAttribution` has `license` and `license_basis`; Knowledge/Study `source_refs` resolve to an attributed source.
5. Knowledge/Study records contain no exam/syllabus keys (`exam`, `placements`, `topic_slug`, `subtopic_slug`, `syllabus`) and no exam codes in IDs.
6. Non-`complete` `definition_status` Concepts are reported as unvetted warnings.

Usage:

```sh
python3 openlearn/work/validate.py                       # defaults to work/normalized
python3 openlearn/work/validate.py openlearn/knowledge   # validate a subtree
```

Exit code is non-zero only for errors; dangling refs and unvetted concepts are warnings so pilots remain usable while incomplete.

## Next actions

1. Decide whether production Concepts must have separate definitional Statements (recommended) or may embed `definition`.
2. If separate definitions are required, tighten `schema-v0.1.json`: require `definition_refs` and drop `definition` in production (keep embedded definitions only for `work/`).
3. Review the normalized pilots for promotion into `knowledge/`, `study/`, and `external/`; promotion should resolve or explicitly whitelist the dangling refs first.
4. Only then plan migration of the 812 `data/concepts/*.json` captures.
