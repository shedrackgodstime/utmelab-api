# Extraction test: Angles (from `math_angles.json`)

Purpose: apply the extraction method to a Mathematics sample. Test composite convention, definitions as Statements, procedures, and scope.

Source: `utmelab-bank/data/concepts/math_angles.json` (“Angles”). Section-capture with objectives/motivating text and definitional/procedural content.

## Extracted entities (table)

| # | Entity (candidate) | Kind (primitive/role) | Exact/short claim (from text) | Scope (implied/stated) | Relations (typed, tentative) | Notes (K/S) |
|---|---|---|---|---|---|---|
| 0 | Section title “Angles” / “Drawing Angles in Standard Position” (headings) | **Study artifact** (container/structure) | Teaching/section titles organizing the treatment. | — | — | Study containers (not Knowledge primitives). “Angles” names the topic referent conceptually but the title itself is organizational. |
| 1 | Angle (geometric concept) | **Concept** (referent) | The geometric object referred to as “an angle” in this treatment (central referent of the section). | Geometry/coordinate geometry context (plane angles implied), introductory mathematics | related-to ray (#2), vertex/endpoint relations; represented in standard position frame (#7) | Knowledge Concept (referent). Note: the section text’s opening definition of angle itself was not fully extracted in this pass (snippet focused on ray); central definition may need separate extraction. |
| 2 | Ray | **Concept** (referent) | As stated by source: “a ray is a directed line segment…” (see note on source error). | Geometry (plane), in this section’s framework | defined-by Statement S1 (#5); has-endpoint (#4) | Core geometric Concept. |
| 3 | Directed line segment (as used in source text) | **Concept** (referent, as named in source) | Named in the source definition: “a ray is a directed line segment.” | Geometry (as presented) | appears in S1 (#5) | Source text uses this phrase; note terminology caution below. |
| 4 | Endpoint (of a ray) | **Concept** (referent/role) | “The first point is called the endpoint of the ray.” (as stated by source) | Geometry | role-of on #2 | Concept with role. |
| 5 | Statement S1 (definition of ray, as stated by source) | **Statement** (definitional; source-fidelity: as stated by source, flagged) | “A ray is a directed line segment. It consists of one point on a line and all points extending in one direction from that point. The first point is called the endpoint of the ray.” (paraphrased) | Geometry (this section’s framework) | defines (#2,#4) | **Source error/terminology caution**: standard geometry distinguishes a ray (one endpoint, extends infinitely in one direction) from a directed line segment (typically two endpoints, directed). The source says “a ray is a directed line segment” then describes a ray-like construction; record as stated by source but flag for verification/correction in a vetted Knowledge layer. |
| 6 | Drawing angles in standard position | **Not extractable from source** (inferred from heading) | Heading implies a method/procedure, but steps not shown in quoted snippets. | Coordinate/plane angle framework (standard position) | — | Do not count as evidence; mark not extractable from source. |
| 7 | Angles in standard position (convention/frame) | **Statement(s)/Conceptual frame** (definitional/conventional), **not a Model** | Convention: place angle with vertex at origin and initial side along the positive x-axis (implied by name/typical usage). | Coordinate geometry / trigonometric angle framework | constrains how #1 is represented | Treated as a **definitional/conventional frame** (Statements fixing how angles are positioned), not a Model (no assumptions/components/predictions/limitations stated as a representational model here). |
| 8 | Motivating story / “In this section you will…” / golfer example | **Study artifact** | Opening motivational text and objectives phrasing. | — | — | Study. |

## What this extraction shows

- **Topic/title is a Study container** (row 0); “Angle” is the Knowledge Concept (row 1). Do not promote the section title to a Knowledge primitive.
- **Definitions central but source-fidelity matters**: ray defined via Statement S1 (as stated by source). The source text says “a ray is a directed line segment…” while describing a ray-like construction — this is a **source error/terminology caution** to flag (standard: ray has one endpoint, extends infinitely; directed line segment usually has two endpoints). Record as stated, verify/correct in a vetted layer.
- **Procedure not extractable here**: “Drawing angles in standard position” inferred from heading only (row 6) — not counted as evidence.
- **“Angles in standard position” is a convention/frame (definitional), not a Model** (row 7): conventionally vertex at origin, initial side on positive x-axis. Use Model only for representational systems with assumptions/components/predictions/limitations.
- **Scope**: geometry/coordinate geometry (plane), introductory math; `subject_area: mathematics` is a view. The central definition of “angle” itself may need separate extraction.

## Comparison

- Strong fit for Concept + Statement (definitions). Procedure evidence was missing from this pass (not extractable from quoted snippets).
- Same bundle pattern as before, but the anchor is the Concept “Angle”, not the title.
- “Standard position” is analogous to “system” (physics): a framing/convention choice, not automatically a Model.