# Cross-pilot review (001–003)

Status: working review. No migration. Based on `pilot-001-newton/`, `pilot-002-economics/`, `pilot-003-math-proof/`.

Purpose: compare the three pilots, identify what held up, and settle the shared schema/reference decisions before moving any records into `knowledge/`.

## Pilots

| Pilot | Source | Main test | Result |
|---|---|---|---|
| 001 | `phy_m42073.json` — Newton’s Second Law | Named law, formulations, system, relation | Concept anchor + one empirical Statement with verbal/mathematical formulations; R1 as Statement supporting a Relation; worked examples Study |
| 002 | `eco_demand_supply_equilibrium.json` — demand/supply/equilibrium | True Model, external placements, Procedure | Model with components/assumptions/predictions/scope; laws empirical; adjustment claims derived; JAMB placements external |
| 003 | `math_integration_fundamental.json` — FTC | Theorem + proof, derived Statements | Theorem Concept anchor + two derived Statements; reusable proof method Procedure; specific derivation Study; assumed concepts flagged |

## What held up

- **Five primitives are sufficient** for these three cases. No sixth primitive was needed.
- **Concept anchor + linked Statements** works for named laws/theorems without inventing a new kind.
- **Statement status** does real work: `empirical` (laws of demand/supply), `derived` (model predictions), `derived/proved` (FTC), `definitional` (equilibrium condition), `asserted` (related-to claim).
- **Formulations** can be grouped under one Statement (Newton verbal + mathematical) without losing source fidelity.
- **Proof** can be represented as a reusable **Procedure** plus a specific **Study derivation**; this avoids treating every proof text as a new primitive.
- **True Model** is distinguishable from a convention/frame: demand/supply has components, assumptions, predictions, scope. “System”/“standard position” did not need Model status.
- **External placements** can live in `external/` records and stay out of Knowledge identity.
- **Source fidelity** flags (as-stated, not extractable, inferred scope) are necessary and usable.

## What strained or needs a decision

### 1. Definitions: embedded vs separate Statements
- Pilot 001: Concept anchor, no separate definitional Statement.
- Pilot 002: definitions embedded in Concept records (`definition` + `definition_fidelity`).
- Pilot 003: concept definitions condensed, assumed concepts flagged.
- **Issue:** the convention says a Statement fixes a Concept, but the pilots vary.
- **Recommendation:** require a separate definitional Statement for any Concept treated as core, or allow embedded definitions only in `work/` pilots. For production, prefer `statement:<concept>-definition` with `status: definitional`.

### 2. Named constructs: Concept anchor vs bundle record
- All three used a Concept anchor (`concept:newtons-second-law`, `concept:fundamental-theorem-of-calculus`).
- **Issue:** “bundle” is a convention, but there is no explicit bundle record; the bundle is implicit in links.
- **Recommendation:** keep Concept anchor + linked Statements/Relations. Do not create a `bundle` entity kind. If a bundle view is needed, generate it from links.

### 3. Assumed/dangling Concepts
- Pilot 003 has `concept:definite-integral` and `concept:antiderivative` with `definition_fidelity: not extractable from this capture`.
- **Issue:** a graph with assumed Concepts is useful but incomplete; dangling definitions can be mistaken for vetted knowledge.
- **Recommendation:** add explicit `definition_status` (`complete | assumed | not_extractable | pending`) on Concept records; forbid treating `assumed/pending` as complete in any release view.

### 4. Study granularity
- Pilots use `study:topic:<slug>` with coarse `block_roles` ranges.
- **Issue:** ranges are enough for pilots, but not for precise attachment/versioning.
- **Recommendation:** keep topic-level Study records now; add optional `block_refs` or per-block Study records later if needed. Do not force per-block records yet.

### 5. Relation reification
- Pilot 001 reified `related-to` for “closely related to the First Law”; the type is vague.
- **Issue:** reifying vague relations adds little; the Statement already carries the claim.
- **Recommendation:** do not reify unless the relation needs its own identity/provenance/attributes; prefer specific relation types (`defines`, `derives-from`, `applies-to`, `part-of`) over `related-to` when possible.

### 6. ID/reference rules
- Pilots use `type:slug` IDs (e.g. `statement:ftc-part1`, `model:demand-supply-equilibrium`).
- **Issue:** no scope in ID; same label in different scopes could collide later.
- **Recommendation:** keep `type:slug` for now but reserve a scope-qualified form (`type:scope:slug`) if collisions appear. Do not encode subject/exam labels in IDs.

### 7. Scope representation
- Pilots use `scope: { text, basis }` where `basis` is stated/inferred.
- **Issue:** conditions (continuity, ceteris paribus, inertial frame) are sometimes inside `text`, sometimes separate.
- **Recommendation:** keep `scope.text` + `scope.basis`; add optional `conditions` array for explicit assumptions/conditions when they matter.

### 8. External layer shape
- Pilot 002/003 store `placements` arrays with `exam`, `subject`, `topic_slug`, `subtopic_slug`.
- **Issue:** exam systems are not yet records; names are strings.
- **Recommendation:** keep arrays for now; later add `external/systems/<system>.json` and reference `system_id` instead of free-text exam names.

### 9. Sources/license
- All three sources are `CC BY-NC-SA 4.0 (non-commercial staging; attribution required)`, not CC BY.
- **Issue:** commercial use is constrained; license must be visible per source and per derived record.
- **Recommendation:** keep `source-attribution.json` per pilot; add `sources/attributions/` records and a `license` pointer on Knowledge records before any release.

### 10. Storage/tooling
- Pilots are flat JSON files; no index, validator, DB, or migration script.
- **Recommendation for next phase:** flat JSON + a manifest/index first; write a small validator for ID resolution, required fields, and dangling refs. Defer DB/tooling until schema v0.1 is accepted.

## Recommended schema v0.1 (to draft next)

Minimum fields:
- Concept: `id`, `kind`, `label`, `scope`, `definition_refs`, `definition_status`, `source_refs`.
- Statement: `id`, `kind`, `about`, `status`, `fidelity`, `scope`, `formulations`, `source_refs`.
- Procedure: `id`, `kind`, `label`, `inputs`, `steps`, `success_criteria`, `scope`, `source_fidelity`, `source_refs`.
- Model: `id`, `kind`, `label`, `purpose`, `components`, `assumptions`, `scope`, `predictions`, `limitations`, `source_refs`.
- Relation: `id`, `kind`, `from`, `to`, `type`, `scope`, `direction`, `provenance`.
- StudyTopic: `id`, `kind`, `title`, `source_capture`, `knowledge_refs`, `block_roles`.
- ExternalPlacement: `id`, `kind`, `source_capture`, `placements`.
- SourceAttribution: `id`, `kind`, `publisher`, `book`, `section`, `url`, `license`, `locator`.
- SourceFidelity: `id`, `kind`, `source_ref`, `items`.

## Decision list before moving into `knowledge/`

1. Definitions: separate Statement or embedded? (Recommendation: separate for production.)
2. `definition_status` vocabulary: `complete | assumed | not_extractable | pending`?
3. Keep `type:slug` IDs or scope-qualified IDs?
4. Keep `scope.text`+`basis`, or add `conditions`?
5. Reify relations only when needed? (Recommendation: yes.)
6. Study: topic-level + block ranges for now? (Recommendation: yes.)
7. External: free-text exam names for now, system records later? (Recommendation: yes.)
8. License: record per source and block commercial release until cleared?
9. Flat JSON + manifest + validator before DB? (Recommendation: yes.)

## What not to do yet

- Do not migrate all `data/concepts/*.json`.
- Do not commit to DB/tooling.
- Do not treat `work/` pilot records as production Knowledge.
- Do not drop source-fidelity/license notes.
