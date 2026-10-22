# UTME Lab API: Consumer-Driven Enhancements Handoff

> **Handoff Target Directory:** `/home/kristency/Projects/utmelab/utmelab-api`  
> **Source Consumer Workspace:** `/home/kristency/Projects/jerry/jamb-quiz` (Next.js 16 + Turso + Live Nigerian CBT Quiz Engine)  
> **Date:** October 2026  
> **Status:** Ready for immediate implementation in a fresh session inside `utmelab-api`.

---

## 1. Executive Summary & Context

During real-world client development of two consumer applications:
1. **`jamb-quiz`** (`/home/kristency/Projects/jerry/jamb-quiz`): Full-featured JAMB CBT practice engine (Next.js 16, LibSQL/Turso cloud, Web Audio sound synthesis, streak tracking, challenge links, admin dashboard).
2. **`Jamb-Lab`** (`/home/kristency/Projects/jerry/Jamb-Lab`): Vite static client.

We identified several architectural friction points and latency bottlenecks when fetching questions, stimuli, and bank updates over Nigerian mobile networks (3G/4G).

This handoff outlines **6 concrete, high-leverage API enhancements** to implement directly in `utmelab-api` to make it a world-class, low-latency API for CBT engines, mobile apps, and self-hosted test centers.

---

## 2. Codebase Architecture Quick-Reference

- **Language & Runtime:** Rust (2021 Edition), Tokio async runtime.
- **Web Framework:** Axum 0.8 with Tower HTTP middleware.
- **Documentation & Spec:** OpenAPI 3.1 generated via `utoipa 5.3` (see [`src/api/openapi.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/api/openapi.rs)).
- **Database:** Turso / libSQL SQLite replica with schema contracts.
- **Key Files & Directories:**
  - `src/api/v1/questions.rs`: List and detail endpoints for questions (`GET /v1/questions`, `GET /v1/questions/{id}`).
  - `src/api/v1/passages.rs`: Passage endpoint (`GET /v1/passages/{id}`).
  - `src/api/v1/papers.rs`: Deterministic paper assembly and scoring (`POST /v1/papers/{exam}/{subject}`, `.../score`).
  - `src/api/v1/subjects.rs`: Subject catalog, syllabus tree, and coverage.
  - `src/api/v1/public.rs`: Keyless discovery surface (`GET /v1/public/summary`, `GET /v1/public/exams`).
  - `src/core/models/wire.rs`: Wire DTOs returned to consumers (`RenderedQuestion`, `Page`, `PublicExam`, etc.).
  - `src/core/catalog.rs`: Pure rendering, pagination bounds, rich-text normalisation.
  - `src/store/catalog.rs`: Turso SQL queries for catalog, questions, passages, and syllabi.
  - `src/api/middleware.rs`: Strong SHA-256 ETag middleware and IP rate-limiting.
  - `site/openapi.json`: Generated OpenAPI spec. **Rule:** Whenever routes, DTOs, or query params change, regenerate with:
    ```bash
    UPDATE_SPEC=1 cargo test openapi
    ```

---

## 3. The 6 Features to Implement

### Feature 1: Embedded Passages (`include_passage=true` or Companion Map)
* **The Problem:** Comprehension and cloze questions return only a `passage_id`. The client must collect IDs and make $N$ individual HTTP calls to `GET /v1/passages/{id}`. Over Nigerian cellular networks, this N+1 latency delays quiz start by several seconds, and a single dropped request causes valid questions to be dropped.
* **Implementation Plan:**
  1. In [`src/api/v1/questions.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/api/v1/questions.rs), add `pub include_passage: Option<bool>` to the `List` query struct.
  2. In [`src/core/models/wire.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/core/models/wire.rs):
     - Update `Page<T>` or `QuestionPageResponse` to optionally include `passages: Option<HashMap<String, Passage>>` (or attach `passage: Option<Passage>` directly onto `RenderedQuestion`).
  3. In [`src/store/catalog.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/store/catalog.rs), when `include_passage` is true:
     - Collect unique `passage_id` values from the retrieved question rows.
     - Execute a batch lookup `SELECT * FROM passages WHERE id IN (...)`.
  4. Also add a batch passage endpoint in [`src/api/v1/passages.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/api/v1/passages.rs):
     - `GET /v1/passages?ids=p1,p2,p3` (comma-separated query parameter).

---

### Feature 2: Quick-Practice / Quiz Sampling Endpoint (`GET /v1/questions/sample`)
* **The Problem:** To serve a 15-question CBT quiz for a subject, consumers currently have to paginate through the entire subject bank (200+ rows), cache the pool in Turso/IndexedDB, and shuffle in local memory. Static web apps and lightweight clients suffer massive cold-start penalties.
* **Implementation Plan:**
  1. In [`src/api/v1/questions.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/api/v1/questions.rs), register route:
     ```rust
     .route("/v1/questions/sample", get(sample))
     ```
  2. Query Parameters:
     ```rust
     #[derive(Deserialize, utoipa::IntoParams)]
     pub struct SampleParams {
         pub exam: String,
         pub subject: String,
         pub count: Option<u32>,        // default 15, max 50
         pub seed: Option<u64>,         // optional deterministic seed for 1-on-1 challenges
         pub verified: Option<bool>,    // default true
         pub include_explanation: Option<bool>,
         pub include_passage: Option<bool>,
     }
     ```
  3. In [`src/store/catalog.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/store/catalog.rs), draw rows either using seeded pseudo-random selection (e.g. `ORDER BY RANDOM()` or deterministic hash shuffle per seed).
  4. Return a ready-to-render array of `RenderedQuestion` plus any required passages in a single round-trip.

---

### Feature 3: Passive `X-Bank-Version` Response Header
* **The Problem:** Consumers must inspect the `ETag` of `/api/v1/public/exams` to know if the bank changed upstream.
* **Implementation Plan:**
  1. In [`src/api/middleware.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/api/middleware.rs):
     - In the response layer, insert a standard header:
       ```rust
       response.headers_mut().insert(
           HeaderName::from_static("x-bank-version"),
           HeaderValue::from_str(&bank_version).unwrap()
       );
       ```
  2. The `bank_version` can be derived from the current catalog hash or Turso `meta` revision already tracked by `Store::version()` / schema contract.
  3. Consumers can now detect bank changes passively on any normal request and invalidate local storage without polling.

---

### Feature 4: Expose `subtopic_id` on `RenderedQuestion`
* **The Problem:** The database table `questions` already has a `subtopic_id` column, but [`RenderedQuestion`](file:///home/kristency/Projects/utmelab/utmelab-api/src/core/models/wire.rs#L147) omits it.
* **Why it is needed:**
  - Granular post-quiz diagnostics (e.g. *"You missed 3 questions in Subtopic: Logarithms"*).
  - Clients can highlight weak spots and offer targeted practice without crawling the full syllabus hierarchy.
* **Implementation Plan:**
  1. Add `pub subtopic_id: Option<String>` to `RenderedQuestion` in [`src/core/models/wire.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/core/models/wire.rs).
  2. In [`src/core/catalog.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/core/catalog.rs), map `q.subtopic_id` in `render()`.
  3. Update tests and regenerate OpenAPI spec (`site/openapi.json`).

---

### Feature 5: Topic-Level Question Breakdown in Discovery
* **The Problem:** The keyless discovery endpoint (`GET /v1/public/exams`) only reports exam- and subject-level verified counts. The full topic breakdown in `GET /v1/subjects/{exam}/{slug}/syllabus` is gated behind API keys (`read:catalog`).
* **Implementation Plan:**
  1. Expose a public syllabus breakdown endpoint or include topic slugs and counts in [`PublicExam`](file:///home/kristency/Projects/utmelab/utmelab-api/src/core/models/wire.rs#L189).
  2. Allows viral quiz landing pages to display topic pickers (e.g., *"Practice 15 questions on Algebra"* or *"Practice 15 questions on Mechanics"*) without burning API quota upfront.

---

### Feature 6: Commercial Paper Assembly with Explanations
* **The Problem:** [`POST /v1/papers/{exam}/{subject}`](file:///home/kristency/Projects/utmelab/utmelab-api/src/api/v1/papers.rs) assembles mocks, but answers and explanations are always withheld. Self-hosted CBT centers or offline hubs cannot score locally without network access to `.../score`.
* **Implementation Plan:**
  1. Add `pub include_explanation: Option<bool>` to `AssembleQuery`.
  2. Gate revealing answers to keys with `SCOPE_READ_CATALOG` / commercial tier.
  3. Also embed passages in `PaperSectionOut` so the assembled paper is 100% self-contained.

---

## 4. Development & Verification Guide

When running in `/home/kristency/Projects/utmelab/utmelab-api`:

```bash
# 1. Typecheck & Build
cargo check

# 2. Run existing test suite
cargo test

# 3. Regenerate OpenAPI documentation whenever endpoints/types change
UPDATE_SPEC=1 cargo test openapi

# 4. Lint with Clippy
cargo clippy --all-targets -- -D warnings
```

### Verification Against Consumer Client
Once changes are made in `utmelab-api`, they can be verified against the live consumer in `/home/kristency/Projects/jerry/jamb-quiz`:
```bash
cd /home/kristency/Projects/jerry/jamb-quiz
npm run test:flow
```
This tests real-world resolution, image marks, passage attachment, scoring, and caching.
