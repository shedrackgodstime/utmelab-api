# Audit (working): Mathematics (samples), against scope-definition.md

Status: draft in `openlearn/`. No migration. Samples from `utmelab-bank/data/concepts/math_*.json`.

## Samples examined

- `math_angles.json` — “Angles” (section-style text: rays, angles in standard position, etc., with learning objectives in blocks)
- `math_binomial_theorem.json` — “Binomial Theorem” (objectives, Pascal’s triangle mention)

## 1) What are the knowledge entities?

- **Concepts**: angle, ray, directed line segment, vertex, initial side, terminal side, standard position (implied), binomial, coefficients, Pascal’s triangle (as an object/conceptual tool referenced), expansion. Also geometric objects and algebraic objects.
- **Statements**: definitions such as “a ray is a directed line segment…” and descriptive statements about how angles are drawn/defined in that section; statements about what Pascal’s triangle helps with (“helps us find the coefficients…”). Some may be definitional, some descriptive/procedural claims.
- **Procedures**: drawing angles in standard position (a method), using Pascal’s triangle to expand a binomial (method) — implied by titles/objectives and text snippets.
- **Models**: coordinate/angle model in standard position (a representational framework), combinatorial/triangular structure of Pascal’s triangle as a model/tool — implicit.
- **Relations**: “consists of one point on a line and all points extending in one direction…” defines ray in terms of line/point/direction (structural/definitional relations); angle formed by rays from a vertex (structural relations); binomial expansion related to coefficients from Pascal’s triangle (epistemic/procedural relation).

## 2) Which primitives do they use?

Concept and Statement are central (definitions). Procedure appears via objectives and method descriptions. Model appears implicitly (standard position framework, Pascal’s triangle structure). Relations are definitional and structural, mostly stated in text.

## 3) What are their scopes?

Scopes are mathematical frameworks: geometry of angles/rays in a plane (Euclidean/coordinate context implied), algebra/combinatorics for binomial theorem (over appropriate number systems/rings in general, but intro scope is typical school algebra). Scope is formal/system/context-dependent; `subject_area: mathematics` is a view. Definitions like “ray is a directed line segment…” are scoped to the geometric framework presented.

## 4) How are they related?

Definitional chains (ray defined via line/point/direction), part/structure relations (angle formed by two rays with common endpoint), procedural relations (use Pascal’s triangle to obtain coefficients). These map to structural/semantic/epistemic/procedural relation families in principle.

## 5) What belongs in Study rather than Knowledge?

Learning objectives and motivational/opening text (“A golfer swings…” in math_angles) are Study. The definitions and method statements are knowledge-leaning (definitional Statements, procedural descriptions). Some explanation text that motivates is Study; the formal/defined content is Knowledge.

## 6) Does anything resist the five primitives?

- **Definitions as first-class**: mathematics relies heavily on definitions (Statements that fix Concepts). The model handles this (Statement with definitional role) — fits.
- **Formal structures (Pascal’s triangle, coordinate system)**: can be seen as Models or as structured objects; calling Pascal’s triangle a “model/tool” is a bit loose but workable. Possibly better as a Model (a structure) or as a Concept with structure — the primitive set is flexible but borderline in naming.
- **Proofs**: not shown in these snippets but common in math; a proof is often a Procedure/derivation yielding a Statement (theorem). Fits the earlier note (Procedure yields Statement) if modeled carefully.
- **Abstract objects introduced by convention**: like “directed line segment” defined in that text — fits Concept+definitional Statement in scope.
No strong resistance from these samples; the main care is distinguishing pedagogical framing from definitional/procedural knowledge and being precise about Models vs structured Concepts.