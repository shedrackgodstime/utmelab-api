# Schema v0.1 (draft)

Status: draft schema for OpenLearn Knowledge/Study/External records. Derived from the three pilots and `pilot-review.md`. Not a migration plan; no records have been moved.

Machine-readable schema: `schema-v0.1.json` (JSON Schema draft 2020-12).
Pilot validation report: `../work/schema-validation-report.md`.

## Design decisions in v0.1

- **Primitives:** Concept, Statement, Procedure, Model, Relation. Named laws/theorems are Concept anchors + linked Statements, not a new kind.
- **Definitions:** production Concepts should point to definitional Statements via `definition_refs`. A temporary `definition` string is allowed for pilots, but must be marked with `definition_status`.
- **Definition status:** `complete`, `assumed`, `not_extractable`, `pending`. Only `complete` may be treated as vetted.
- **Statement status:** `definitional`, `descriptive`, `normative`, `derived`, `empirical`, `provisional`, `asserted`.
- **Statement role:** optional `law`, `theorem`, `principle`, `hypothesis`, `fact`, `prediction`, `condition`, `definition`, `other`.
- **Source fidelity:** `as-stated`, `paraphrased`, `verified`, `corrected`, `not-extractable`.
- **Scope:** `text` + `basis` (`stated`, `inferred`, `mixed`, `not_extractable`) + optional `conditions`.
- **IDs:** `type:slug` with optional namespace segments, e.g. `statement:ftc-part1`, `study:topic:newtons-second-law`. No exam/subject labels in IDs.
- **Relations:** reify only when the link needs identity/provenance/attributes. Prefer specific relation types over `related-to`.
- **Study:** `StudyTopic` for section/topic containers; `StudyDerivation` for specific proof/derivation walkthroughs. Reusable proof methods are Procedures.
- **External:** placements live in `ExternalPlacement` records, not in Knowledge records.
- **Sources:** `SourceAttribution` and `SourceFidelity` records; license is required on attribution records.
- **Storage:** flat JSON first. `schema_version` is optional in v0.1 (required in production later).

## Common ID pattern

`^[a-z]+(:[a-z0-9][a-z0-9_-]*)+$`

Examples: `concept:demand`, `statement:law-of-demand`, `procedure:locate-equilibrium`, `model:demand-supply-equilibrium`, `study:topic:demand-supply-equilibrium`, `external:placements:eco_demand_supply_equilibrium`.

## Scope object

```json
{
  "text": "Newtonian/classical mechanics (introductory)",
  "basis": "inferred",
  "conditions": ["inertial frame", "non-relativistic speeds"]
}
```

- `text` required.
- `basis` required: `stated`, `inferred`, `mixed`, `not_extractable`.
- `conditions` optional.

## Concept

Required: `id`, `kind` (`Concept`), `label`, `scope`, `definition_status`, `source_refs`.
One of: `definition_refs` (preferred) or `definition` (temporary/pilot).
Optional: `linked_statements`, `distinguished_from`, `notes`.

```json
{
  "id": "concept:demand",
  "kind": "Concept",
  "label": "Demand",
  "definition_refs": ["statement:demand-definition"],
  "definition_status": "complete",
  "scope": { "text": "Introductory economics", "basis": "inferred" },
  "source_refs": ["source:openstax-m63601"]
}
```

## Statement

Required: `id`, `kind` (`Statement`), `about`, `status`, `fidelity`, `scope`, `source_refs`.
One of: `text` or `formulations`.
Optional: `role`, `block_refs`, `supports_relation`, `notes`.

```json
{
  "id": "statement:law-of-demand",
  "kind": "Statement",
  "about": ["concept:demand", "concept:quantity-demanded"],
  "status": "empirical",
  "role": "law",
  "fidelity": "as-stated",
  "scope": {
    "text": "Introductory economics; other demand determinants held constant",
    "basis": "stated"
  },
  "text": "A rise in price almost always decreases quantity demanded.",
  "source_refs": ["source:openstax-m63601"]
}
```

`formulations` item: `{ type: "verbal"|"mathematical"|"other", text, block_refs? }`.

## Procedure

Required: `id`, `kind` (`Procedure`), `label`, `inputs`, `steps`, `success_criteria`, `scope`, `source_fidelity`, `source_refs`.
Optional: `notes`.

## Model

Required: `id`, `kind` (`Model`), `label`, `purpose`, `components`, `assumptions`, `scope`, `predictions`, `limitations`, `source_refs`.
Optional: `notes`.

`assumptions` item: `{ text, basis }` where `basis` is `stated|inferred|mixed|not_extractable`.

## Relation

Required: `id`, `kind` (`Relation`), `from`, `to`, `type`, `scope`, `direction`, `provenance`, `source_refs`.
Optional: `notes`.

`direction`: `directed`, `symmetric`, `unspecified`.

## StudyTopic

Required: `id`, `kind` (`StudyTopic`), `title`, `source_capture`, `knowledge_refs`, `block_roles`, `source_refs`.
Optional: `notes`.

## StudyDerivation

Required: `id`, `kind` (`StudyDerivation`), `label`, `knowledge_refs`, `block_refs`, `summary`, `source_refs`.
Optional: `notes`.

## ExternalPlacement

Required: `id`, `kind` (`ExternalPlacement`), `source_capture`, `placements`.
Optional: `notes`.

`placements` item: `{ exam, subject, topic_slug, subtopic_slug (string or null) }`.

## SourceAttribution

Required: `id`, `kind` (`SourceAttribution`), `publisher`, `book`, `section`, `url`, `license`, `license_basis`, `locator`.
Optional: `notes`.

## SourceFidelity

Required: `id`, `kind` (`SourceFidelity`), `source_ref`, `items`.
Optional: `notes`.

`items` item: `{ ref, fidelity, note }`.

## Validation rules (not all expressible in JSON Schema)

1. Referenced IDs should resolve within the loaded record set; allowed exceptions are `definition_status: assumed|pending` and `fidelity: not-extractable`.
2. No exam/syllabus identifiers in Knowledge records. Those belong in `ExternalPlacement`.
3. Extracted Knowledge/Study records should carry at least one `source_refs` entry.
4. Only `definition_status: complete` Concepts may be treated as vetted in release views.
5. Only Statements with `fidelity: verified` may be treated as vetted claims; `as-stated`/`paraphrased` remain source claims.
6. License must be recorded on every `SourceAttribution`; commercial release is blocked until licenses are cleared.
7. `Model` requires all six representational fields; otherwise use a convention/Statement/Procedure.

## Open issues for v0.2

- Whether `definition_refs` should be mandatory for all Concepts (no embedded definitions).
- Whether `Statement.role` should be a closed enum.
- Relation type vocabulary (currently free text).
- Whether `schema_version` should be mandatory on every record.
- Whether Study needs per-block records or block ranges are enough.
- How to represent bundle views without a bundle entity.
