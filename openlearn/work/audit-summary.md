# Audit summary (working): Physics, English, Mathematics

Status: draft in `openlearn/`. No migration. Based on `audit-physics.md`, `audit-english.md`, `audit-mathematics.md`.

## What the three audits show (together)

- The five primitives (Concept, Statement, Procedure, Model, Relation) are usable as lenses across all three domains, but they are **not yet sufficient as a drop-in ontology for the current corpus captures**. The current `data/concepts/*.json` files are mostly **source/section captures** (Study-adjacent containers) with embedded teaching text, objectives, and external `placements`, not clean Knowledge-layer entities.
- **Concepts and Statements** appear clearly in all three: physics quantities/laws-names and claims; English categories and descriptive/usage claims; math definitions and definitional statements. Definitions are common and fit “Statement with definitional role” fixing a Concept in scope.
- **Procedures** appear explicitly in objectives/method language and implicitly in explanations (calculations, “use Pascal’s triangle…”, strategy hints). Distinguishing method (Procedure) from a narrated walkthrough (Study) is needed.
- **Models** are often implicit: Newtonian framework, EM field picture, “system” choice (physics); descriptive patterns/classification schemes (English, borderline); coordinate/standard-position framework, Pascal’s triangle as structure/tool (math, borderline). The primitives fit if we allow Model as a structured representation, but texts rarely label models cleanly.
- **Relations** are mostly implicit in prose (defined-via, related-to, category membership, applies-to in wording). Typing them requires careful scope and direction choices.

## Extraction tests (concrete)

See: `openlearn/work/extract-newtons-second-law.md`, `openlearn/work/extract-english-emphatic-stress.md`, `openlearn/work/extract-mathematics-angles.md`.

- **Newton’s Second Law (physics)**: composite convention holds as a first pass — “Newton’s Second Law of Motion” is a **Concept (label) bundled with Statements** (relational/characterizing + clarifications like “change in motion ≡ change in velocity”, “change in velocity means… by definition acceleration”) plus an implied scope (Newtonian/classical mechanics). No new primitive required. Strain: “system” in the title is a **modeling/application choice** (better treated carefully, not as a plain quantity Concept).
- **English emphatic/contrastive stress**: same bundle pattern (topic label + Concepts like sentence/emphatic/contrastive stress and categories + descriptive Statements). Key difference: status is **descriptive/usage (“helps”, “usually”)**, so Statement status must be explicit (not only truth-apt like some physics laws).
- **Math angles**: definitions map cleanly to **Statement (definitional) fixing Concepts** (ray, endpoint). “Drawing angles in standard position” is a **Procedure**. “Angles in standard position” is a **representational frame/modeling choice** (borderline like “system”), not obviously a new primitive but needs careful modeling.

## Domain-specific frictions

- **Physics**: named laws/framework bundles read like composites (Model/framework + Statements + labels). Units/symbols are roles of Concepts. Motivating anecdotes and “previous section” links are Study.
- **English**: heavier Study/teaching packaging; descriptive/usage status (“usually”) differs from hard laws; categories can be read as Concepts or classification structure — needs care. Strategies/objectives are Study or Procedure-presentation.
- **Mathematics**: heavy definitional load fits well; proofs (not shown) would be Procedure/derivation yielding Statement (theorem). Structured tools/frames (Pascal’s triangle, standard position) sit near Concept vs Model boundary.

## Scope observations

- Constitutive scopes are frameworks/conditions (Newtonian mechanics, classical EM, geometric/frame context, algebraic/combinatorial scope, English usage framework) — often implied, not explicit. `subject_area`/subject labels are views, not constitutive scope.
- External `placements` inside current captures are **extrinsic alignment** (exam/syllabus refs) and belong outside Knowledge core per scope-definition.md; they should not be treated as Knowledge relations.

## What resists or strains the five primitives (from these samples)

- Composites: named laws/theory/topic bundles, and modeling/frame choices (“system”, “standard position frame”) presented in titles/text.
- Implicit/untagged relations and models (common in textbook prose).
- Study vs Knowledge boundary is fuzzy in heavily pedagogical text (especially English).
- No clear need for a sixth primitive from these tests, but a **modeling convention for bundles and for modeling/frame choices** is needed (and Statement status must be representable, especially for descriptive/usage claims).

## Implication for next work

- Do **not** migrate the 812 `data/concepts/*.json` captures into Knowledge entities yet. Conventions (working) are now recorded in `openlearn/conventions/conventions.md` (operational a–d) and `openlearn/conventions/scope-definition.md` (boundaries/primitives/scope): (a) named bundles, (b) modeling/frame choices, (c) Statement status + source-fidelity vocab, (d) separating Study vs Knowledge in captures. These still need testing against more samples.
- Optional follow-ups (if desired): extract one more physics sample with a clear Procedure/theorem-proof shape (e.g. `phy_work_energy.json`) and one more English sample with explicit strategy/procedure text (e.g. `eng_cloze_procedure.json`) to stress-test Procedure boundary further.
- The five primitives remain a workable lens; the main gaps are structural/conventional (bundles, status, explicit relations/models, scope capture), not missing primitive kinds.