# Extraction test: Emphatic and Contrastive Stress in English (from `eng_emphatic_contrastive_stress.json`)

Purpose: apply the same extraction method used for Newton’s Second Law. Test the composite convention and see how primitives fit a language/usage domain (with heavier Study packaging and descriptive/normative status).

Source: `utmelab-bank/data/concepts/eng_emphatic_contrastive_stress.json` (“Emphatic and Contrastive Stress in English”). Section-capture style blocks (headings + prose). Snippets below are representative from the file content seen in audit.

## Extracted entities (table)

| # | Entity (candidate) | Kind (primitive/role) | Exact/short claim (from text) | Scope (implied/stated) | Relations (typed, tentative) | Notes (K/S, status) |
|---|---|---|---|---|---|---|
| 1 | Sentence stress (in English sentences) | **Concept** (referent) | Heading/topic: “Sentence Stress…”; described as helping signal meaning in English sentences. | English (variety/register not specified in source snippets; must be named if it matters, e.g. Nigerian/British English) sentence-level prosody in an instructional context | has-types/kinds: emphatic stress (#3), contrastive stress (#4) (implied); relates-to meaning signaling (#7) | Knowledge-leaning referent; treatment is descriptive/teaching. |
| 2 | Stress assignment pattern (content vs function words) | **Statement** (descriptive/generalization; source-fidelity: paraphrased) | “In English, stress in sentences helps signal meaning. Content words such as nouns, main verbs, adjectives, adverbs, and question words are usually stressed, while function words (pronouns, prepositions…) are usually not.” (paraphrased from snippet) | English usage in instructional scope (variety unspecified) | describes (#1); classifies into #5, #6 | Status descriptive/generalized (“helps”, “usually”). Record as stated by source unless verified. |
| 3 | Emphatic stress | **Concept** (referent/type) | Named type under sentence stress (“Emphatic Stress” section heading/content). | English sentence prosody, instructional scope (variety unspecified) | type-of/kind-of (#1) | Type/category of sentence stress. |
| 4 | Contrastive stress | **Concept** (referent/type) | Named type (“Contrastive Stress” in heading/context). | English sentence prosody, instructional scope (variety unspecified) | type-of/kind-of (#1) | Type/category; contrastive use noted informally. |
| 5 | Content words (class) | **Concept** (category/class) | Examples listed: nouns, main verbs, adjectives, adverbs, question words (usually stressed). | English grammar/prosody categories in this framework | contrasted/classed against #6 | Category Concept; illustrative list. |
| 6 | Function words (class) | **Concept** (category/class) | Examples implied: pronouns, prepositions (usually not stressed). | English grammar/prosody categories in this framework | contrasted with #5 | Category Concept. |
| 7 | Meaning signaling by stress | **Statement** (descriptive claim about effect) | “helps signal meaning” (stated as effect). | English instructional scope (variety unspecified) | effect-of patterns (#1/#2) on meaning interpretation | Descriptive claim; “meaning signaling” is the referent area. |
| 8 | Section headings / “Sentence Stress, Emphatic Stress and Contrastive Stress” title block | **Study artifact** (container/structure) | Teaching structure/headings organizing the topic treatment. | — | — | Study container (not a Knowledge primitive). |
| 9 | Implied procedures/strategies (from headings/objectives context) | **Not extractable from source** | No explicit steps/procedure text shown in quoted snippets. | — | — | Do not count as evidence; mark not extractable from source. |

## What this extraction shows

- **Topic title is a Study container**, not a Knowledge primitive. The title bundles Concepts (#1,#3,#4), descriptive Statements (#2,#7), category Concepts (#5,#6), and Study structure (#8).
- **Status matters (English-specific)**: “helps”, “usually” are descriptive/generalizations; prescriptions like “should” would be normative. Statement status/strength and source-fidelity (paraphrased here) must be explicit.
- **Scope must name variety/register when it matters**: snippets say “In English…” but do not specify variety; scope is recorded as underspecified.
- **No new primitive obvious**. Row 9 was inferred from headings/context and is **not extractable from source** in this pass.

## Notes vs Newton’s Second Law test

- Same bundle pattern (named treatment → multiple entities + Study), confirming topic titles should not be promoted to Knowledge primitives.
- Reinforces need for Statement status and careful scope labeling.