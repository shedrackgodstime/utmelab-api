# Mathematics coverage audit: JAMB Mathematics, WAEC General Mathematics, WAEC Further Mathematics

Date: 2026-11-10

This audit follows the project contract: every concept is restructured from a
source with URL and locator recorded in the concept file. Nothing is invented.
Topics/subtopics with no matching sourced concept are marked `no_source` or left
unmapped pending sourcing.

Machine-readable mapping: `data/concepts/audit-math.json` (gitignored staging).  
Production catalog snapshot: `data/prod-catalog-subtopics-math.json` (read-only fetch).  
Canonical notes: `data/generated-notes/prod-topic-notes-math.json` (preflight-valid).

## Sources

| Publisher | Books / collections | Recorded licence/status | Concepts | Locator |
|---|---|---|---|---|
| OpenStax | *Contemporary Mathematics* (`osbooks-contemporary-mathematics`) | CC BY-NC-SA 4.0 (non-commercial staging; attribution required) | 17 | CNXML module `index.cnxml` per concept `source_attribution` |
| OpenStax | *College Algebra* (`osbooks-college-algebra-bundle`) | CC BY-NC-SA 4.0 (non-commercial staging; attribution required) | 27 | CNXML module `index.cnxml` per concept |
| OpenStax | *Calculus Vol. 1* (`osbooks-calculus-bundle`) | CC BY-NC-SA 4.0 (non-commercial staging; attribution required) | 7 | CNXML module `index.cnxml` per concept |
| OpenStax | *Introductory Statistics* (`osbooks-statistics`) | CC BY-NC-SA 4.0 (non-commercial staging; attribution required) | 3 | CNXML module `index.cnxml` per concept |
| OpenStax | *University Physics* (`osbooks-university-physics-bundle`) | CC BY-NC-SA 4.0 (non-commercial staging; attribution required) | 2 | CNXML module `index.cnxml` per concept |
| OpenStax | *Prealgebra* (`osbooks-prealgebra-bundle`) | CC BY-NC-SA 4.0 (non-commercial staging; attribution required) | 1 | CNXML module `index.cnxml` per concept |
| OpenStax | *Contemporary Mathematics* 3.7 Clock Arithmetic (web) | CC BY 4.0 (web book; attribution required) | 1 (`math_modular_arithmetic`) | Section 3.7 Clock Arithmetic (`https://openstax.org/books/contemporary-mathematics/pages/3-7-clock-arithmetic`) |
| OpenStax | *Algebra and Trigonometry 2e* 12.1-12.3 Conic Sections (web) | CC BY 4.0 (web book; attribution required) | 1 (`math_conic_sections`) | Sections 12.1 The Ellipse, 12.2 The Hyperbola, 12.3 The Parabola |
| OpenStax | *College Algebra 2e* 1.1 Real Numbers: Algebra Essentials (web) | CC BY 4.0 (web book; attribution required) | 1 (`math_binary_operations`) | Section 1.1, Using Properties of Real Numbers (`https://openstax.org/books/college-algebra-2e/pages/1-1-real-numbers-algebra-essentials`) |

**Total math concepts:** 60 (`math_*`), all with recorded provenance. 57 concepts currently carry JAMB/WAEC mathematics placements. Added in this pass: `math_modular_arithmetic` (WAEC modular arithmetic), `math_conic_sections` (WAEC further coordinate geometry, conic sections), and `math_binary_operations` (JAMB binary operations properties).

## Production scope (authoritative)

| Exam / Subject | Topics | Subtopics |
|---|---:|---:|
| JAMB / mathematics | 23 | 77 |
| WAEC / general-mathematics | 30 | 100 |
| WAEC / further-mathematics | 21 | 70 |

## Coverage status (from `audit-math.json`, updated)

| Subject key | Exam | Topics | Covered | Thin | No source | Subtopics |
|---|---|---:|---:|---:|---:|---:|
| mathematics | JAMB | 23 | 17 | 5 | 1 | 77 |
| general-mathematics | WAEC | 30 | 28 | 0 | 2 | 100 |
| further-mathematics | WAEC | 21 | 16 | 0 | 5 | 70 |

### JAMB Mathematics - topic status
- **Covered (mapped to sourced concepts):** number-bases, indices-logarithms-and-surds, sets, polynomials, variation, inequalities, progression, binary-operations (foundational properties of operations: closure in real-number context, commutativity, associativity, distributivity, identity and inverse elements, sourced from OpenStax College Algebra 2e 1.1; JAMB expects simple cases in binary-operation contexts), matrices-and-determinants, coordinate-geometry, differentiation, application-of-differentiation, integration, representation-of-data, measures-of-location, permutation-and-combination, probability.
- **Thin (partial/specifics may need additional sourcing):** fractions-decimals-approximations-and-percentages (general foundations present; JAMB-specific applications such as simple/compound interest, profit/loss, VAT, shares, ratio/rate in exam form, significant figures/decimal places/percentage error procedures need explicit sourced coverage), euclidean-geometry (points/lines/angles/triangles/area covered; circles/cyclic quadrilaterals/intersecting chords, full polygon scope and construction need more), mensuration (areas/volumes/surface areas covered; earth as sphere/longitudes-latitudes and some arc/sector/chord specifics need more), trigonometry (ratios/unit circle/functions covered; bearings, elevation/depression in exam context, sine/cosine rules, triangle solutions/graphs need more), measures-of-dispersion (location measures mapped; range, mean deviation, variance, standard deviation need explicit sourced coverage).
- **No source (currently):** loci.

### WAEC General Mathematics - notes/gaps
- Broadly mapped where existing OpenStax concepts align (number/indices/logs/sets/surds/sequences, algebra/functions/equations/graphs, coordinate/trig/geometry/mensuration, statistics/probability, etc.).
- **Newly covered:** `waec-modular-arithmetic` (3 subtopics) sourced from OpenStax Contemporary Mathematics 3.7 (`math_modular_arithmetic`).
- **Mapped (thin):** `waec-sine-cosine-and-tangent` mapped to trigonometry concepts (ratios/unit circle/functions); trig tables and full exam-context coverage may need additional sourced material. `waec-change-of-subject-of-a-formula-relation` mapped to algebra/manipulation concepts.
- **Unplaced/missing notes (catalog/data issues):** 6 subtopics under `waec-angles-of-elevation-and-depression` in production catalog appear misgrouped (differentiation/statistics subtopics); placements withheld pending catalog clarification.
- **No source / not yet mapped:** `waec-construction`/`waec-loci`-related gaps as applicable. WAEC topic statuses/notes require refinement to per-subtopic accuracy.

### WAEC Further Mathematics - notes/gaps
- Mapped where aligned: sets/surds/functions/polynomials/rational functions/indices/permutation/binomial (thin)/sequences-series/calculus/trigonometry/matrices (thin)/vectors/probability/statistics/statics (thin) etc.
- **Newly mapped:** `waec-co-ordinate` now includes `math_conic_sections` (parabola, ellipse, hyperbola sourced from OpenStax Algebra and Trigonometry 2e 12.1-12.3) alongside straight-line coordinate concepts (thin; verify all subtopics).
- **Unmapped/partial:** dynamics subtopics with corrupted/misaligned catalog entries, and topics without matching sourced concepts.
- Requires per-subtopic audit refinement and additional sourcing.

## Placements and notes (current)

- **Placements:** 57 math concepts have JAMB/WAEC mathematics placements (subtopic-level, derived from audit mappings and validated against production slugs). Some heuristic/broad placements need per-subtopic review for accuracy.
- **Canonical notes (synthesized, one per placement):** `data/generated-notes/prod-topic-notes-math.json` - **233 notes, preflight-valid** (`python3 scripts/validate_notes.py` OK)
  - JAMB / mathematics: 76 notes (1 subtopic without sourced concepts remains without notes: `loci` x1)
  - WAEC / general-mathematics: 94 notes (6 subtopics missing notes: 6 misgrouped catalog subtopics under `waec-angles-of-elevation-and-depression`)
  - WAEC / further-mathematics: 63 notes (7 subtopics missing notes, including misaligned/corrupted dynamics subtopics)
- Notes are grounded in sourced concepts with provenance in `sources`, exam-polished formatting, no em/en dashes or meta boilerplate; worked examples included where extractable/derived from sourced content.

## Validation

- `python3 scripts/validate_concepts.py` -> 527 files, 0 errors
- `python3 scripts/validate_notes.py data/generated-notes/prod-topic-notes-math.json` -> OK (233 notes)
- `data/concepts-ingestion-manifest.json` refreshed (527 concepts)

## Gaps and next actions (contract-aligned)

1. **Refine mapping accuracy:** per-subtopic review of `audit-math.json` and concept placements (remove over-broad mappings, ensure each subtopic is correctly served).
2. **Source missing/thin content:** find reliable sources (with URL/locator/licence) for `no_source` and thin topics (loci, construction, interest/profit-loss/VAT/shares in exam form, bearings/elevation-depression/longitudes-latitudes, circle theorems/constructions, dispersion details, etc.). Record in concepts/audit/docs; do not invent.
3. **Resolve catalog anomalies:** verify/correct handling of misgrouped WAEC subtopics (e.g. under `waec-angles-of-elevation-and-depression`, dynamics currency-like subtopics) against authoritative production intent.
4. **Regenerate notes:** after mapping/sourcing updates, regenerate and validate canonical notes; run parity checks against existing production math notes where available.
5. **Ingest:** import notes (`cargo run -- import-notes data/generated-notes/prod-topic-notes-math.json` or scoped bundles) and upload concept objects per manifest when ready.

All content remains sourced and provenance-recorded; gaps are explicit.