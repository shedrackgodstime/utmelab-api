# OpenLearn (knowledge product root)

Project name: **OpenLearn** (working name). Directory: `openlearn/`.
Status: initialized product directory. Work-in-progress transition docs live in `work/`. No migration/code yet.

## What this is

`openlearn/` is the product directory for an exam-independent educational knowledge asset. The core is the referent; external systems (JAMB, WAEC, NECO, syllabi, professional bodies) are referrers via mappings.

Central rule: the core defines and teaches knowledge; external systems hold their own trees/requirements and reference the core through records stored outside it. Deleting an external system must leave the core unchanged.

## Directory map

- `knowledge/` — core: Concepts, Statements, Procedures, Models (Relations reified only when needed) in `concepts/`, `statements/`, `procedures/`, `models/`, `relations/`.
  - `knowledge/bundles/` — named composites (Concept anchor + linked entities + scope; **not** a sixth primitive).
- `study/` — core teaching artifacts (topics, explanations, examples, media) that attach to knowledge by id.
- `external/` — external referrers/mappers only (`systems/`, `placements/`, `mappings/`). Exam ids/weights/years stay here, never in core identity.
- `sources/` — attribution/license (`attributions/`) and source-fidelity notes (`fidelity/`).
- `conventions/` — working rules: `scope-definition.md` (boundaries/scope/primitives), `conventions.md` (operational conventions a–d), and `schema-v0.1.md`/`.json` (draft record schema).
- `work/` — transitional audits/extractions/plans, plus `normalized/` pilot copies and the schema/cross-record validator (`validate.py`).

## Core vs external

- Knowledge entities are identified by meaning + scope, not by exam/syllabus/lesson/learner path. Subject labels are views/tags only.
- Study teaches/communicates knowledge; worked examples are usually Study (walkthrough/execution/result). A reusable general method may be a Procedure only when stated as such.
- External mappings live in `external/`, not in knowledge records.

## Primitives (provisional)

1. Concept — the referent.
2. Statement — asserted/defined claim (explicit status/strength + source-fidelity when extracted).
3. Procedure — how a result is achieved.
4. Model — structured representation (only with assumptions/components/scope/limitations/predictions in the representational sense).
5. Relation — typed link (direction/scope/provenance where relevant).

Named laws/principles/topics are composites/bundles, not a sixth primitive.

## Where to start

- Read `conventions/scope-definition.md` for boundaries and notes.
- Read `conventions/conventions.md` for operational rules (bundles, frames/Model, status/fidelity, Study extraction).
- See `work/` for audits/extractions that produced the conventions.
- See `work/pilot-review.md` for the cross-pilot findings (`pilot-001-newton/`, `pilot-002-economics/`, `pilot-003-math-proof/`).
- See `work/normalized/` for the schema-v0.1-normalized pilot copies, and run `python3 work/validate.py` for schema plus cross-record checks.

## Not done yet

Flat JSON + draft schema + local validator only; no DB/index chosen. No decision on concrete representation of Study pointers or external alignments in practice. Classification boundary cases remain flagged in `work/` extractions. No records promoted into `knowledge/`. No migration of `utmelab-bank/data/concepts/*.json` yet.
