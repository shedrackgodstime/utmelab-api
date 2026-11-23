# Audit (working): Physics, against scope-definition.md

Status: draft in `openlearn/`. No migration, no schema changes. This tests the five primitives (Concept, Statement, Procedure, Model, Relation) on representative Physics material drawn from `utmelab-bank/data/concepts/phy_*.json` (sampled titles below). Purpose: see what fits, what is strained, what is clearly Study/external.

## Samples examined (illustrative)

- `phy_acceleration.json` — “Average and Instantaneous Acceleration”
- `phy_force_on_conductor.json` — “Magnetic Force on a Current-Carrying Conductor”
- `phy_m42073.json` — “Newton’s Second Law of Motion: Concept of a System”
- `phy_first_law.json` — “Newton’s First Law” (and cross-check with `phy_m42130.json` title/statement text pattern)
- Also noted titles present: `phy_m42326.json` (electric potential in uniform field), others. These are OpenStax-derived section captures stored as concept records in the current corpus (see scope doc: current captures conflate section/teaching capture with “concept” label in that pipeline).

Note: the files are section-level captures (learning objectives, prose, formulas in text). The audit asks what knowledge entities appear *in the material*, not only what the filename calls a “concept”.

## 1) What are the knowledge entities?

From the samples, recurring entities (by role in the text):

- **Concepts (referents)**: acceleration, velocity, time, change in motion, force, net external force, system, mass (implied), magnetic field, current-carrying conductor, moving charges, electric field, potential difference/voltage (in related material), inertia (named in titles), Newton’s laws as named laws/framework items.
- **Statements (asserted/defined)**: definitions/formulations such as “average acceleration is the rate at which velocity changes…” with formula $ā=\Delta v/\Delta t$; Newton’s first law stated as a body at rest/motion remains unless acted on by net external force (with notes about “remains”, constant velocity); Newton’s second law described as relating force and changes in motion (cause/effect framing in that section) leading toward $F=ma$ in broader context (implied). Also statements like “moving charges experience a force in a magnetic field…” and qualitative field/loop statements in the conductor text.
- **Procedures (methods)**: problem-solving/strategy language appears in titles elsewhere (`phy_m42076.json` “Problem-Solving Strategies”) and implicitly: how to compute average acceleration from given $v,t$; how to reason about whether net force is zero (first law applications) — often presented as steps in teaching but the method itself is a Procedure candidate.
- **Models/representational structures**: Newtonian framework (laws of motion) as a model/scope for classical mechanics in these sections; the magnetic field/loop picture and compass deflection as a representational model of field produced by current (described qualitatively); “system” as a modeling choice in second law (defining what is included). These are not always named “Model” in text but function as structured representations with scope/assumptions.
- **Relations (typed links)**: acceleration defined in terms of velocity/time (semantic/definitional link); acceleration is change in motion/equivalent to change in velocity (epistemic/definitional framing); force related to changes in motion (causal/relational in wording, but epistemically “states cause and effect relationship” in that text) — needs careful typing; first law preserves status quo of motion (relational). Many links are implicit.

Also present as **non-knowledge-in-core roles** in the same files: learning objectives, narrative connectors (“in the previous section…”), pedagogical prompts — these are Study/structure, not knowledge entities.

## 2) Which primitives do they use?

- **Concept**: heavily used (named quantities, objects, laws-names as referents).
- **Statement**: heavily used (definitions, law statements, qualitative claims). Many are definition-like or law-like with status/role.
- **Procedure**: present implicitly (calculation of average acceleration, application steps). Explicit strategy titles exist elsewhere but the sampled section texts mix method hints into prose (Study-tinged).
- **Model**: present implicitly (Newtonian dynamics framework, field-loop representation, “system” modeling choice). The corpus files do not label them as Model entities; they appear as context/scope.
- **Relation**: present implicitly and explicitly in words (“related to”, “is the rate of which…”, “equivalent to”, “causes/effect relationship” stated informally). Rarely typed as explicit relation records in the current captures.

## 3) What are their scopes?

- Classical mechanics / Newtonian dynamics for acceleration, velocity, force, first/second law sections (with Newtonian assumptions implied: non-relativistic, macroscopic in typical intro framing) — scope is a framework/scope of validity.
- Electromagnetism context for magnetic force on a current-carrying conductor and related field descriptions (scope: EM fields, currents) — different domain scope but still physics frameworks.
- “Uniform electric field” in `phy_m42326` title implies a modeling/scope condition (idealization) — scope/conditions attached to that treatment.
- The current corpus records carry `subject_area: "physics"` and OpenStax source attribution; that is a broad label/view, not the constitutive scope. The constitutive scopes are the physical frameworks (Newtonian mechanics, classical EM, etc.), which are only implied in text.

## 4) How are they related?

Implicit relations observed:
- Acceleration defined via velocity and time (semantic/definitional).
- Change in velocity means acceleration (definitional/equivalence in meaning stated).
- Newton’s second law related to first law (structural/epistemic relation stated in text).
- Net external force relates to change in motion / acceleration (causal language in prose, but should be typed carefully: in Newtonian model, force relates to acceleration via law/model).
- Magnetic field produced by current; force on moving charges in wire (procedural/causal chain described qualitatively).

Most are expressed in prose, not as typed relation records. The scope-definition relation families (structural/semantic/epistemic/procedural/genetic-historical/external alignment) fit in principle, but current captures do not encode them explicitly.

## 5) What belongs in Study rather than Knowledge?

Clearly Study (teaching artifacts) in these files:
- Learning objectives lists.
- Narrative transitions (“In the previous section…”, “Experience suggests…” as pedagogical framing).
- Worked phrasing aimed at intuition (“importance of understanding…”).
- The section title as a teaching unit label in this pipeline (a Study/container label in current storage), though it points to knowledge content.
- Problem-solving strategy content (when present) is often Study/pedagogical method presentation, even if it references a Procedure.

Borderline:
- “Experience suggests…” sentences: pedagogical lead-in, not the law statement itself (the law is stated after). The law statement is Knowledge (Statement) in scope; the anecdote is Study.
- Qualitative explanations (“compass needle experiences a force that aligns…”) can be Study explanations of a model/phenomenon; the underlying model/claims are Knowledge components.

## 6) Does anything resist the five primitives?

Some tensions/strains:

- **Named “laws” as entities**: “Newton’s First Law”, “Newton’s Second Law” appear as names. Are they Concepts, Models, or composites (a model/law bundle)? The scope doc says “theory is a composite…” and laws can be Statements with status/role or part of models. In these texts they function like named anchors (referents) that bundle statements and a framework — borderline between Concept (named law) and part of a Model/frame. Needs careful modeling (possibly a Model/framework entity plus Statements, with the name as a label/referent).
- **“System” (in second law section)**: described as a modeling choice (“First, what do we mean by a change in motion?…” leads into defining system context) — this is closer to a Model/component/assumption aspect than a simple Concept in isolation. The text says “Concept of a System” in title, mixing Concept and modeling concept.
- **Fields/loops as representational pictures**: qualitative descriptions of magnetic field loops are part of a representational Model; the text presents them pedagogically. Hard to split cleanly into “the Model claim” vs “the explanation” without more structure.
- **Units and symbols** (e.g. $ā$, m/s^2 implied): treated as part of Statements/Concept roles in text; not a separate primitive here but important. The primitive set did not list “Quantity/Unit” as a kind except as “quantity or unit: concept with measurement role” in the earlier note — so Concept-with-role is the intended handling (acceptable if noted).
- **Observations/examples in text** (“everyday conversation…”, compass deflection story): these are pedagogical examples/observations used for teaching (Study) or as motivating observations; not the same as formal knowledge Statements. The scope doc’s note about observations being careful applies.

Overall: the five primitives are usable as lenses, but **named laws/framework bundles** and **modeling choices presented in section titles/prose** show that real texts mix levels (a “law” name can point to a composite). The current corpus format (section capture with blocks, revision_summary as note-like fields, placements inside records) conflates Study containers, teaching text, and embedded “placements” (external refs) — which matches the scope doc’s finding that these are not yet clean knowledge entities.

## Summary (Physics)

- Fits reasonably: Concepts, Statements, and (implicitly) Procedures/Models/Relations are all present in content.
- Main friction: composites (named laws/frameworks), implicit relations, and the mix of Study scaffolding with knowledge content in the same captured blocks.
- Scope is mostly implicit (Newtonian mechanics, classical EM) under a broad `subject_area: physics` label; constitutive scopes need to be made explicit, not inferred from subject labels.
- The corpus’s current “concept record” shape is a source/section capture artifact (Study-adjacent container) plus external placements, not yet a clean Knowledge-layer entity set. That aligns with the scope doc’s migration note.