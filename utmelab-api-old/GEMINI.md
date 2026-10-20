# UTME Lab Repository Guidelines & Standards

This document establishes architectural invariants, database boundaries, and writing standards for the `utmelab-api` and `utmelab-pipeline` codebases.

---

## 1. System Architecture & Separation

1. **Decoupled Architecture**:
   - `utmelab-api`: High-performance Rust Axum server serving the CBT exam platform, OpenAPI documentation, stateless paper assembly, and scoring.
   - `utmelab-pipeline`: Independent Python 3.12 data engineering package (managed with `uv`) responsible for harvesting, Gate 0 mechanical filtering, multimodal AI verification, and approved queue staging.

2. **Database Isolation**:
   - **Production Turso DB (`TURSO_PROD_DB_*`)**: Strictly READ-ONLY for standard pipeline operations. It supplies authoritative syllabus data (`topics`, `subtopics`, `objectives`).
   - **Pipeline Turso DB (`TURSO_PIPELINE_DB_*`)**: Isolated staging database holding `scrape_runs`, `harvest_staging`, `review_queue`, `approved_questions`, `approved_passages`, `approved_verifications`, and `pipeline_metrics`.
   - **Production Sync**: Only explicit executions of `pipeline sync-to-prod --confirm` are authorized to commit approved items to production.

3. **Schema & Content Parity**:
   - All questions promoted by the pipeline must match the Rust `Question` model and compute an identical SHA-256 `content_fingerprint` using the `\u001f` delimiter.

4. **Zero API Cost**:
   - The AI verification engine exclusively utilizes OpenCode free models (`openrouter/openrouter/free`, `opencode/space-bunny-free`, `opencode/muse-spark-1.3-contributor-free`) with graceful fallback.

---

## 2. Writing Style & Prose Constraints

All documentation, user-facing copy, explanations, reports, and AI generation prompts must adhere to these writing constraints:

1. **The Em Dash Ban**:
   - Zero em dashes (`—`) or en dashes (`–`) are permitted.
   - Do not use hyphen substitutes (`--` or ` - `).
   - Use periods to break thoughts into distinct sentences, or use commas, colons, or standard conjunctions (`and`, `but`, `so`, `because`).

2. **Banned AI Vocabulary & Clichés**:
   - Eliminate filler words: *delve into*, *testament to*, *tapestry*, *beacon*, *game-changer*, *pivotal*, *paramount*, *in conclusion*, *furthermore*, *moreover*, *it is worth noting*, *navigate the landscape*, *harness the power*, *foster*, *plethora*, *myriad*, *seamlessly*.

3. **Cadence & Tone**:
   - Write with a direct, confident, active human voice.
   - Vary sentence lengths aggressively: alternate short, punchy statements with longer explanatory sentences.
   - Get straight to the factual payload without throat-clearing padding.
