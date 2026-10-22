# Findings During Usage & Consumer Feedback

> Collected during real-world client integration with `jamb-quiz` (Next.js 16 + Turso) and `Jamb-Lab` (Vite static client).  
> **Full Architecture & Implementation Guide:** See [HANDOFF.md](../HANDOFF.md).

---

## 1. Subtopic ID Exposure on Questions
**Status:** Completed & Verified  
**Observation:** The database table `questions` holds a `subtopic_id` column, but `RenderedQuestion` previously omitted it from wire payloads.  
**Delivered Solution:**
- Added `subtopic_id: Option<String>` to `RenderedQuestion` in `src/core/models/wire.rs`.
- Passed through `q.subtopic_id` in `render` within `src/core/catalog.rs`.
- Powers granular post-quiz diagnostics and topic practice without requiring reverse mapping.

---

## 2. Reading Passages Overhead (N+1 Round-Trip Latency)
**Status:** Completed & Verified  
**Observation:**
In `GET /api/v1/questions`, comprehension and cloze questions return a `passage_id`. Clients had to make separate requests to `GET /api/v1/passages/{id}` for every distinct stimulus, causing latency on mobile networks.  
**Delivered Solution:**
- Added `include_passage=true` parameter to `GET /api/v1/questions` and `GET /api/v1/questions/{id}`.
- Populated `rendered_question.passage` directly on each question and included a companion `passages: HashMap<String, Passage>` map in the `Page<T>` envelope.
- Implemented batch passage retrieval and subject prefetching on `GET /api/v1/passages` (`?ids=p1,p2` or `?exam=JAMB&subject=english`).

---

## 3. Quick-Practice / CBT Sampling Endpoint
**Status:** Completed & Verified  
**Observation:**
To serve a 15-question CBT quiz for a subject, consumers had to paginate through the entire subject bank, buffer rows in memory or local Turso replicas, and shuffle locally.  
**Delivered Solution:**
- Added `GET /api/v1/questions/sample`.
- Supports `exam`, `subject`, `count` (1 to 50, default 15), `seed` for reproducible challenges, `verified`, `topic`, `subtopic`, `year`, `include_explanation`, and `include_passage`.
- Returns ready-to-render sets with optional embedded passages in a single call.

---

## 4. Passive Bank Version / Revision Header
**Status:** Completed & Verified  
**Observation:**
Consumers had to inspect the `ETag` of `/api/v1/public/exams` or poll keyless discovery endpoints to detect upstream bank updates.  
**Delivered Solution:**
- Added `bank_version` middleware in `src/api/middleware.rs` attaching `x-bank-version` to every response.
- Exposed `x-bank-version` in CORS `expose_headers` in `src/api/mod.rs` so browser clients can read the header directly.
- The version reflects the Turso replica revision or schema contract version.

---

## 5. Topic-Level Question Counts on the Discovery Surface
**Status:** Completed & Verified  
**Observation:**
The syllabus tree endpoint `/api/v1/subjects/{exam}/{slug}/syllabus` was gated behind API keys, while public discovery `/api/v1/public/exams` only reported exam and subject totals.  
**Delivered Solution:**
- Added keyless `GET /api/v1/public/syllabus/{exam}/{slug}` in `src/api/v1/public.rs`.
- Returns the complete syllabus topic tree with live question counts, public CORS access, and no key required.

---

## 6. Paper Assembly and Scoring with Explanations
**Status:** Completed & Verified  
**Observation:**
`POST /api/v1/papers/{exam}/{subject}` generated mocks, but answers and explanations were withheld, preventing offline test hubs from grading locally. Furthermore, scoring required individual question detail fetches to display post-exam corrections.  
**Delivered Solution:**
- Added `include_explanation=true` and `include_passage=true` to `AssembleQuery` on `POST /api/v1/papers/{exam}/{subject}`.
- Added optional `include_explanation: Option<bool>` to `ScoreRequest` on `POST /api/v1/papers/{exam}/{subject}/score`.
- When scoring with `include_explanation: true`, `ScoredQuestion` includes `answer` and `explanation`, returning marking results and working in one round-trip.
