# Scope definition (working draft)

Status: draft in `openlearn/`. This project is not migrating anything yet. This document defines boundaries only. No code, no schema changes, no migration work.

## Purpose

Define what belongs to the educational resource core and what belongs outside it, so the collection can serve any curriculum or learner path without being defined by any consumer (examinations, boards, ministries, institutions). Examination systems such as JAMB and WAEC are initial consumers and reference this core; they do not define it.

## Central rule

The core is the referent. External systems are referrers.

- The core defines and teaches knowledge.
- External systems hold their own trees, terminology, requirements, and revisions.
- External systems reference the core through explicit mapping records stored outside the core.
- Deleting an external system must leave the core unchanged. Deleting a core entity may leave external references dangling, which is the correct failure signal.

## The two questions the collection must answer

1. What do we know, and how can we teach it?
2. Which external systems reference what we know?

These are separate concerns. The first is core. The second is the external mapping layer.

## Core boundaries

### Knowledge (core)

Knowledge entities are independent of any examination, syllabus, lesson plan, or learner path. Knowledge does not need JAMB, WAEC, or any university to exist.

A knowledge entity is a unit that can be identified, asserted or defined, connected to other units, and evaluated for validity within a stated scope, independent of any learner, lesson, or examination system.

Tests for a knowledge entity:

1. It can be true or false, or it can be a definition.
2. It has a scope in which it holds.
3. It would survive deletion of every exam board, textbook, and lesson.
4. It is referenced by identity, not by location in a syllabus tree.

### Study (core teaching artifacts)

Study materials teach or communicate knowledge. They are pedagogical artifacts. A definition, law, or statement does not change because a lesson changes; an explanation, walkthrough, or example may change. The same sentence can appear in both roles, but its role differs: in Knowledge it asserts or defines; in Study it explains or demonstrates.

Study artifacts attach to knowledge entities by reference (and later by versioned pins in releases), not by owning exam topics.

### What stays out of the core

The following belong outside the core (external systems or mapping layer), not inside knowledge or study definitions:

- exam identifiers, paper numbers, years, weights, syllabus topic codes used as core identity
- syllabus tree structure owned by an external body as the core ontology
- curriculum sequencing as a claim about logical prerequisite (pedagogical sequencing is Study or external)
- exam-specific past items whose identity depends on an external system (those are external artifacts; reusable practice items with no board/year may be treated as core teaching/assessment resources only if they do not depend on an external identity)

If a field would still mean something after JAMB disappeared, it is a candidate for the core. If it would not, it belongs outside.

## Scope vs subject classification

- Scope is constitutive. Define scope generally as: the framework, formal system, practice, conditions, or jurisdiction within which a knowledge entity has meaning or validity. Scope describes where it holds (for example velocity within classical mechanics; a rule within a legal jurisdiction; a procedure under stated conditions).
- Subject is classification and navigation (a view). Physics, economics, accounting, mathematics, and English are labels attached for organization. They are not the definitional ground of the knowledge entity. For language/usage domains, scope must name the **variety/register/context** when it matters (e.g. Nigerian English vs British English stress patterns), not just “English”.

Rules:

- Do not derive identity from a subject label.
- A single knowledge entity may be used across subjects; do not duplicate identities because applications differ (for example exponential growth across math, biology, economics).
- Represent subject labels as views or tags when needed, not as the primary identity or as proof of scope.

## Entity kinds (small, stable)

Use a small set of primitives. Status and role are distinct from kind.

Primitives (working set, to be tested across disciplines before treating as complete):

1. Concept: a named idea with a definition (unit of reference).
2. Statement: a claim that can be true or false, or a definition that fixes a concept.
3. Procedure: a method that achieves a result, with inputs, steps, and success condition.
4. Model: a structured representation with assumptions, components, and scope.
5. Relation: a typed link between entities (reify only when provenance, scope, or versioning is required).

The set is provisional. Test it against different disciplines (including phenomena, events, observations, and classifications). Do not assume it is exhaustive; add a new primitive only if no composition of existing primitives fits without distortion.

### Notes: Concept (working)

- Concept is the referent; a Statement says something about it. Identity should be anchored to scope plus meaning, not to a name string alone. Do not create a new Concept identity solely because of different formulations/levels in the same scope when a typed relation can express the difference; do not merge across different scopes/frameworks without explicit alignment relations.

### Notes: Statement (working)

- Definitions, facts (by status), laws (science norms vs legal norms by scope), theorems, hypotheses, and principles are typically Statements with status/role, not separate primitive kinds.
- Statements are generally tied to Concepts/relations/models and to a scope; a bare unscoped claim is usually not a useful core entity.
- Validity is scope-relative. Same wording can be different Statements across scopes; the same content may hold in multiple scopes only when conditions/definitions align.
- Observations are not always mere evidence: an observation/measurement record can be an independently identifiable record (conditions, provenance, uncertainty) that supports or challenges Statements; treat carefully rather than auto-classifying all observations as “just evidence” text.
- Normative statements (scientific, mathematical, legal, ethical) can all be represented as Statements if scope and status are made explicit and not conflated (e.g. “usually stressed” is descriptive/usage; “should be stressed” is normative/prescriptive). Evidence/proof/authority/justification differ by scope.
- Distinguish: the Statement being evaluated; the evidence supporting/challenging it; the source from which evidence originated.
- Operational requirements (status/strength, source-fidelity, representations, source attribution/license notes) are specified in **Conventions (c)** and the **Refinements** bullets on source claim vs vetted knowledge; see those for working vocab and rules.

### Notes: Procedure (working)

- Procedure is the method/specification (inputs, conditions, steps/rules, outputs/outcomes, success criteria) in a scope. Statement asserts/defines; Procedure prescribes/describes how to achieve a result.
- Algorithms, mathematical methods, laboratory techniques, and practical skills can be the same primitive kind (Procedure), differing by scope and formality.
- Distinguish Procedure (the method), Implementation (a particular realization), Execution (a particular occasion/performance/run), and Result (what an execution produced). Do not merge these identities.
- A documented Procedure may not capture all tacit skill; represent articulated method and performance criteria without claiming completeness of human competence.
- Conditions and success criteria are essential knowledge about the Procedure (applicability limits, assumptions, acceptance criteria), not only teaching material.

### Notes: Model (working)

- Model is a structured representation of some aspect of a domain (phenomena, system, process, structure) built to explain, predict, simulate, or organize understanding; it has components, relations among components, assumptions, and a stated scope of applicability.
- **Use Model only when that representational role is present.** See **Conventions (b)** for detailed distinctions (frames/conventions like “angles in standard position”, analytical/system choices) versus true Models.
- A Model differs from a single Concept or from an unstructured collection of Statements: it organizes entities and claims into a coherent structure with purpose (explanation/prediction/simulation). Scientific theories (as composites), mathematical structures, economic models, conceptual diagrams used representationally, and simulations (as computational realizations/models in context) can be treated as Model-kind entities in this working set, with care about composites like “theory”.
- Models may contain or reference other knowledge entities (Concepts, Statements, Procedures, other Models). Make explicit: assumptions, components, scope, limitations, and predictions/claims (Statements supported or generated). Keep these attached to the Model with scope noted.
- A Model is not necessarily a collection of pre-existing knowledge entities: it may introduce its own components, variables, assumptions, and relationships (e.g. abstract agents in an economic model). Such introduced components may need independent identities if referenced elsewhere; do not require every component to pre-exist as a Concept.
- A diagram is not automatically a Model. It may represent a Model, illustrate a Concept, communicate a Procedure, or visualize data; distinguish the underlying Model from its visual representation (Media). A simulation is not necessarily the Model itself; it can be an implementation/computation of one (distinguish Model identity from a particular run/output).
- Models may evolve (formulations/versions). Preserve the ability to distinguish different formulations/versions without treating every revision as an entirely unrelated Model unless meaning/scope changed fundamentally.

### Notes: Relation (working)

- A Relation is a typed link between knowledge entities (or in some cases between an entity and a scope context) that expresses how they are connected (structural, semantic, epistemic, procedural, genetic/historical, or external alignment as defined). Its type gives the connection meaning (not just two identifiers). Examples: a quantity linked by a unit relation, a law linked by applies-to to a scope/framework, a concept linked by depends-on to another concept.
- Relation differs from a Statement: a Statement asserts/defines (truth-apt or definitional-in-force); a Relation is the typed connection (endpoints + type, optionally scope/provenance/attributes). A Statement may state a relation, but the structured link is the Relation.
- Not all relationships are intrinsic to Knowledge: only intrinsic families (structural/semantic/epistemic/procedural/genetic-historical in the knowledge layer) belong in Knowledge. Extrinsic relations (e.g. placed in a syllabus unit of an exam, or pedagogical sequencing imposed by a curriculum) belong to external mapping/alignment or to Study/external layers.
- **Directionality**: relation types must define whether direction matters. Inverses (e.g. part-of vs has-part) are not interchangeable labels; model direction explicitly.
- **Scope**: a relation may be valid in one framework/scope but not another (especially in scientific, mathematical, and historical knowledge). Record scope when it matters.
- **Reification**: do not turn every relation into a full entity. Reify only when it needs an independent identity, provenance, scope, versioning, or additional attributes. Otherwise keep it as a typed edge.
- Direction, scope, meaning, and provenance matter in general: many types are directional; scope constrains validity; type carries meaning; provenance (asserted by/when/source) is important, especially for contested or externally sourced links. Represent these when reified or when required.

Subtypes, statuses, and roles are not new kinds. Examples (classification, not new primitives):

- Definition: a statement that fixes a concept.
- Law: ambiguous. In science, an empirical regularity/predictive statement; in law, a norm with institutional authority. Treat carefully by scope and status, do not collapse.
- Principle: a foundational role in a framework (role/status).
- Theorem: a statement derived in a formal system with a proof procedure (statement + status/role context).
- Hypothesis: a statement with provisional status.
- Fact: a statement with observational warrant (status).
- Theory: a composite (model plus accepted statements, evidence, scope/history), not an atom in the same way.
- Quantity or unit: concept with measurement role.
- Skill: procedure with performance criterion.
- Example: usually Study unless a canonical instance is explicitly modeled.
- Classification: a model or a set of relations.

Formal representations (symbols, notation) are part of representation of a statement or concept, not a separate primitive kind by default.

## Relationships

Relationships are typed. Prefer typed edges; reify as entities only when needed (provenance, scope, versioning).

Families (working):

1. Structural: is-a, part-of, instance-of, member-of, composes.
2. Semantic: contrasts-with, equivalent-to, symbol-for, measures, represents.
3. Epistemic: defines, states, assumes, explains, predicts, supports, contradicts, derived-from, generalizes, specializes.
4. Procedural: prerequisite-for (logical), used-in, solves, applies-to, requires.
5. Genetic/historical: causes, precedes, influenced-by, discovered-by.
6. External alignment: aligned-to, assessed-by, placed-in (kept outside the core).

Important distinctions:

- Intrinsic vs extrinsic: intrinsic relations hold in the knowledge/model layer; extrinsic relations (for example “in Unit 2 of syllabus X”) belong to external mapping/alignment, not to core knowledge identity.
- Logical prerequisite vs pedagogical sequencing: logical prerequisite is epistemic/procedural in scope of validity; pedagogical sequencing is Study or external.

## Study boundary notes

Apply the test: would this content change if the learner, lesson, or exam changed?

- **Topic/lesson titles and section headings are Study organizational containers**, not Knowledge primitives. Do not create artificial Knowledge entities just to represent textbook headings (e.g. “Emphatic and Contrastive Stress in English”, “Angles” as a chapter title). A topic may point to many Knowledge entities (Concepts, Statements, Procedures, Models) and to Study materials; the title itself belongs in Study/organization unless it names an independently defined referent that is itself a Knowledge Concept.
- Knowledge records what is defined, asserted, or established within a scope. Definitions can be revised, refined, or replaced as frameworks evolve; what matters is that a definition is a knowledge assertion (or a definition that fixes a concept), not a pedagogical artifact.
- Study records how that knowledge is communicated, explained, demonstrated, or taught. Explanations, walkthroughs, and most demonstrations are Study and may change with audience or lesson design.
- Worked examples: the procedure or case structure may involve knowledge; the walkthrough is Study. Model explicitly if needed, but do not let a walkthrough become the identity of knowledge.
- Diagrams/media illustrate; claims they illustrate are Knowledge (media is separate in practice but the claim is core).
- Misconceptions are often Assessment or Study artifacts, not Knowledge definitions.
- Exam items whose identity depends on an external system are external; generic practice items with no board/year may be core teaching/assessment resources only if identity is independent.

## External mapping layer (separates concerns)

Curricula and examinations (JAMB, WAEC, NECO, university syllabi, professional bodies, ministries, etc.) are external. They:

- own their structures and revisions,
- reference core entities through explicit mapping records (alignment/placement records),
- may carry weights, years, paper numbers, and their own identifiers outside the core.

The core does not store exam_weight, past_paper_year, or syllabus_topic_code as core fields.

## What this document is not

- It is not a migration plan.
- It is not a schema change.
- It is not an implementation decision for repositories or storage.
- It is a boundary and vocabulary draft to test against real material before any migration.

## Preserved decisions (working foundation)

- Core and external systems remain independent.
- Scope, not subject, provides conceptual context.
- Knowledge and Study remain separate.
- The five primitives remain provisional.
- Relationships are typed.
- Examination mappings remain external.
- No migration or implementation decisions yet.

## Where we are now (working set)

Knowledge primitives (provisional, not a proven universal ontology):

1. **Concept** — the referent.
2. **Statement** — what is asserted or defined (with explicit status/strength and source-fidelity when extracted).
3. **Procedure** — how a result is achieved.
4. **Model** — a structured representation (used only when assumptions/components/predictions/limitations/scope in that representational sense apply).
5. **Relation** — a typed connection (its type gives meaning; direction, scope, and provenance matter).

### Refinements from audits/tests (working)

- **Named knowledge constructs (laws/principles/theories)**: treat names as bundle anchors in composites (Concept/label + linked Concepts/Statements/Relations + scope), not as a sixth primitive. See **Conventions (a)**.
- **Analytical constructs vs choices vs boundaries**: classify by role (Conceptual analytical construct vs Procedure/decision step vs boundary/distinction) when evidence allows; do not collapse into one label. See **Conventions (a),(b)**.
- **Source claim vs vetted knowledge**: keep source text separate from vetted/corrected claims; record fidelity and flags, and capture attribution/license when known (not yet a full Sources layer). See **Conventions (c),(d)** for operational rules.
- Controlled vocab remains provisional; the working set is listed in **Conventions (c)**.

### Operational conventions (moved)

Status/fidelity vocab, bundle rules, Model/frame distinctions, and Study/Knowledge extraction rules now live in `conventions.md` (see **Conventions (a)–(d)**), to avoid duplication. This document keeps boundaries, scope, primitives, and notes; apply the operational conventions from `conventions.md` when classifying material.

## Next step (recommended, not executed here): test the model against actual knowledge

Test the primitives together on representative material from subjects already in view (Physics, Chemistry, Biology, Mathematics, English, Economics, Accounting, Business Studies). Start with one subject at a time, beginning with Physics, then deliberately test against English and Mathematics (contrasting disciplines to expose weaknesses early).

For each subject/sample, examine actual educational material and identify:

1. What are the knowledge entities?
2. Which primitives do they use?
3. What are their scopes?
4. How are they related?
5. What belongs in Study rather than Knowledge?
6. Does anything resist the five primitives?

Do not force every source record to produce exactly one concept, statement, relation, and scope. Some records may contain several knowledge entities; others may contain none independently identifiable. The audit should reveal actual structure, not confirm a structure already decided.

If the set of primitives or relation families cannot classify without adding a new primitive, revise the model. Do not migrate the 812 existing concept captures until this boundary is tested and accepted.