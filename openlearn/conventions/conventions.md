# Conventions (working)

Status: working rules, still being tested. Boundaries/primitives live in `scope-definition.md`; this file holds the operational conventions (a–d) used to classify real material.

## (a) Named bundles (topic/law/principle/theory)

Do not promote a teaching title or named-construct label to a Knowledge primitive by itself. Represent as:

- a named **Concept/label anchor** (only if it refers to an independently definable referent in scope),
- linked **Concepts**, **Statements** (with status/fidelity), **Procedures** when present, **Relations**,
- an explicit **scope**,
- (optional) Study pointers.

For named laws/principles, store constitutive/characterizing Statements under the anchor. No sixth primitive.

## (b) Modeling/frame choices (Model boundaries)

Distinguish:

1. **Model** — structured representational system: purpose, assumptions, components, scope, limitations/predictions. Use Model only when that representational role is present.
2. **Definitional/conventional frame** — e.g. “angles in standard position” (vertex at origin, initial side on positive x-axis), or “system” as the chosen set of objects in mechanics. Usually **Statements/conventions fixing a Concept or analysis setup in scope**, not a Model unless the full representational apparatus is present.
3. **Analytical/procedural choice** — e.g. choosing which system to analyze. A **Procedure/step** or guidance (often Study), not a Concept and not a Model.

Do not label frames/choices as Models by default.

## (c) Statement status + source-fidelity

**Status/strength** (when relevant): `definitional`, `descriptive` (incl. usage/generalization like “usually”), `normative/prescriptive`, `derived/proved`, `provisional/hypothetical`, `empirical/empirically established`, `asserted` (generic when source is unspecified).

**Source-fidelity**: `as-stated`, `paraphrased`, `verified`, `corrected`.

Rules:
- Flag source errors/loose phrasing rather than silently normalizing.
- Multiple verbal/mathematical (or other) formulations may represent the **same underlying Statement** in a scope; record them as formulations, not automatically separate claim identities, unless they state different claims.
- Sentences asserting relationships are typically **Statements** that support/assert a Relation; the Relation is the typed link (endpoints + type, plus scope/provenance when reified).

## (d) Separating Study text from Knowledge claims (current captures)

In `data/concepts/*.json` (section-capture style), treat as **Study** unless they state/define vetted Knowledge:

- titles/headings used as containers
- learning objectives
- motivational stories
- walkthrough narration
- “in this section…” text
- exercises/questions/prompts
- pedagogical advice

Extract **Knowledge** only where text asserts/defines/derives claims about Concepts/Statements/Procedures/Models in a scope (even if phrased pedagogically): definitions, laws/claims, procedures stated as method, explicit scopes/assumptions. When ambiguous, default to Study and note uncertainty.

**Worked examples:** a specific worked example is usually Study (walkthrough/execution/result in that instance). A reusable general method may be a Procedure only when stated as a method.

**Assertions about relations:** see (c); statements support/assert Relations, they do not *become* the Relation.

## Source attribution/license

Record source attribution/license when known (e.g. OpenStax content is CC BY) in `sources/attributions/` and note it in extractions. Not yet a full modeled Sources layer.
