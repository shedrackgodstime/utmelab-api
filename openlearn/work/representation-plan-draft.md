# Representation plan (draft, docs-only)

Status: draft in `openlearn/`. **No migration, no schema/code changes.** This describes a minimal target shape for Knowledge-layer records derived from current `utmelab-bank/data/concepts/*.json` section captures, guided by `openlearn/conventions/scope-definition.md` and extractions.

## Goals
- Separate **Knowledge** (core, exam/curriculum-independent) from **Study** (pedagogical artifacts) and from **External alignment** (`placements`, syllabus/exam refs).
- Use the five primitives as lenses (Concept, Statement, Procedure, Model, Relation) plus the conventions in `scope-definition.md` (named bundles, modeling/frame choices, Statement status/fidelity, Study/Knowledge separation, stated vs inferred scope).
- Preserve **source-fidelity** and **attribution/license** notes (e.g. OpenStax CC BY) until a full Sources layer exists.

## Minimal entity shapes (conceptual)

### Concept
- `id` (stable, scope-aware), `label` (name), `scope` (framework/conditions/variety as applicable; mark stated vs inferred), `definition_refs` (Statement ids with `status=definitional`), `notes`, `source_refs` (with fidelity/attribution pointers).

### Statement
- `id`, `text_or_representation` (verbal/math/other), `status` (from working vocab: `definitional|descriptive|normative/prescriptive|derived/proved|provisional/hypothetical|empirical/empirically established|asserted`), `source_fidelity` (`as-stated|paraphrased|verified|corrected`), `scope`, `about` (Concept/Model/Procedure ids), `formulations` (optional list linking representations of the same underlying claim), `notes` (flags like loose phrasing).

### Procedure
- `id`, `title/label`, `inputs`, `steps_or_method` (structured or referenced text), `success_criteria/outputs`, `scope`, `status/context`, `source_refs`.  
- **Rule:** specific worked examples are **Study** (walkthrough/execution/result) unless a reusable general method is explicitly extracted.

### Model
- `id`, `label`, `purpose`, `assumptions`, `components` (Concept/other ids), `scope`, `limitations/predictions` (linked Statements), `source_refs`.  
- **Rule:** only when representational apparatus is present (see `scope-definition.md` Conventions b). Frames/conventions like “standard position” or “chosen system setup” are usually Statements/conventions or Procedure choices, not Models.

### Relation (typed link)
- `from`, `to`, `type` (from working families: structural/semantic/epistemic/procedural/genetic-historical), `scope` (if relevant), `direction` (explicit), `provenance/source_refs`. Reify only if needed (versioning/attrs).  
- **Rule:** sentences asserting relationships are typically **Statements** that support/assert the Relation; the Relation is the typed link.

### Bundle (named construct, e.g. “Newton’s Second Law”)
- Not a sixth primitive. Represent as: **Concept (label anchor)** + linked Statements + linked Relations + explicit scope (+ optional Study pointers). Example mapping below.

## Mapping from current `data/concepts/*.json` (section captures)

Current files are mostly **Study-adjacent containers** (title, objectives, blocks of prose/examples, `placements`, `subject_area`, `deep_context`). A future migration would:
- Treat **titles/headings as Study containers** (do not become Knowledge primitives by default).
- Extract **Knowledge** only where text asserts/defines/derives claims in scope (definitions, laws, procedures stated as method, explicit assumptions). Mark ambiguous text as **Study**.
- Move `placements` (exam/syllabus refs, board/year/topic codes) to an **External alignment layer** (outside core). `subject_area` becomes a **view/tag**, not constitutive scope.
- Record **source attribution/license** (e.g. OpenStax CC BY) in source metadata/notes until a Sources model exists.
- Preserve **source_fidelity** (`as-stated|paraphrased|verified|corrected`) and flags for errors/loose phrasing.

## Example (illustrative): Newton’s Second Law (from `openlearn/work/extract-newtons-second-law.md`)
- **Concept**: “Newton’s Second Law of Motion” (label anchor), scope `Newtonian/classical mechanics (introductory, inferred context)`.
- **Statements (examples)**:
  - S2a (verbal formulation) + S2b (mathematical formulations) treated as **formulations of the same underlying empirical Statement** (`status=empirical`, `source_fidelity=as-stated`), constitutive of the Concept; relates Concepts like acceleration, net external force, system, mass.
  - R1-like claim (“closely related to First Law”) is a **Statement** asserting a relation to Concept “Newton’s First Law of Motion”; the typed **Relation** (e.g. `related-to`/`contextualized-by`, direction/scope noted) may be reified if needed.
  - S4 (“change in velocity means… acceleration”) is a **Statement** flagged (`source_fidelity=as-stated`, caution noted) for verification.
- **Concepts referenced**: change in motion, velocity, acceleration, external/net external force, system (analytical construct), mass, weight/unit definitions as Statements where applicable.
- **Procedures**: general method to apply $F_{net}=ma$ could be a Procedure if extracted explicitly; the lawn mower/rocket sled blocks are **Study** walkthroughs/examples in the current capture.
- **Study**: objectives, motivational text, worked example narration, conceptual questions/exercises prompts (blocks 0–1,39–66,68–124 in that file) remain Study.
- **Unresolved/notes**: system boundary classification unresolved in extraction; block coverage not fully enumerated (64,67,68–124); scope assumptions (inertial/non-relativistic) not stated explicitly in read blocks.

## What this plan does NOT do (yet)
- No file moves, no JSON reshaping, no new repos/tables implemented.
- No attempt to auto-convert all 812 captures; conversions would be manual/curated with conventions applied.
- No final ontology for Relation types beyond working families; no final Sources/License schema beyond notes.

## Next concrete steps (when ready)
1. Validate this shape against 2–3 more extracts (e.g. `phy_work_energy.json`, an Economics section, a math theorem with proof).
2. Decide a minimal storage/pointer model for Study attachments and External alignment (separate from Knowledge records).
3. Pilot-map 3–5 captures end-to-end (Knowledge entities + Study pointers + external refs stripped) and review edge cases.
4. Only then consider tooling/migration design.