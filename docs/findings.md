# Findings During Usage & Consumer Feedback

> Collected during real-world client integration with `jamb-quiz` (Next.js 16 + Turso) and `Jamb-Lab` (Vite static client).  
> **Full Architecture & Implementation Guide:** See [HANDOFF.md](../HANDOFF.md).

---

## 1. Subtopic ID Exposure on Questions
**Status:** Under Consideration / Verification  
**Observation:** The database has a `subtopic_id` column, but `RenderedQuestion` does not currently expose it in wire responses.  
**Why it matters:**  
Exposing `subtopic_id` on questions allows consumer apps to:
- Deliver granular post-quiz diagnostics (e.g. *"You scored 12/15; your weak spot is Subtopic: Change of Base in Logarithms"*).
- Power topic-targeted practice without requiring clients to fetch the full syllabus tree and reverse-map question IDs.
- Group questions by curriculum strand on mock exam review screens.

---

## 2. Reading Passages Overhead (N+1 Round-Trip Latency)
**Observation:**  
In `GET /api/v1/questions`, English comprehension and cloze questions return only a `passage_id` (e.g. `"p_comprehension_01"`).  
Consumers must extract unique passage IDs and fire separate requests to `GET /api/v1/passages/{id}` for every distinct stimulus.  
**Impact on Consumer:**  
On mobile 3G/4G networks in Nigeria (high latency / packet drop), this N+1 waterfall delays quiz start by seconds. If a single passage request fails, valid questions must be discarded because comprehension questions are unanswerable without their passage.  
**Proposed Solutions:**
- **Option A (Preferred):** Add `include_passage=true` parameter to `GET /api/v1/questions`. Return an attached `passages: HashMap<String, Passage>` map in the `QuestionPageResponse` envelope (or attach directly on `RenderedQuestion`).
- **Option B:** Provide a batch passage endpoint: `GET /api/v1/passages?ids=p1,p2,p3` or `POST /api/v1/passages/batch` accepting JSON array of IDs.

---

## 3. Quick-Practice / CBT Sampling Endpoint
**Observation:**  
To assemble a standard 15-question CBT quiz for a subject, consumers currently must:
1. Fetch the entire subject question pool (multiple pages of 50–200 questions).
2. Buffer or persist all questions locally in a database (Turso / IndexedDB).
3. Randomly shuffle and slice the questions on the client or server.  
**Impact on Consumer:**  
Lightweight consumers, serverless functions, or static clients with limited storage cannot easily buffer full subject pools and suffer high cold-start latencies.  
**Proposed Solution:**  
Add a randomized sampling endpoint:
```
GET /api/v1/questions/sample?exam=JAMB&subject=mathematics&count=15&seed=42&verified=true
```
- Returns a clean, ready-to-render practice set in a single HTTP call.
- Accepting an optional `seed` allows viral 1-on-1 challenges where two students compete on the exact same randomized question set.

---

## 4. Passive Bank Version / Revision Header
**Observation:**  
The API supports ETag content-versioning on GET endpoints. However, to discover if the question bank was updated upstream (e.g. typos fixed, new 2025 questions verified), consumers must inspect the ETag of `/api/v1/public/exams` or make explicit polling calls.  
**Proposed Solution:**  
In `src/api/middleware.rs`, attach a passive header on every successful response:
```http
X-Bank-Version: 682b9614a04e8142
```
This allows consumer apps to continuously inspect bank freshness from any regular background query and invalidate stale local caches automatically without extra requests.

---

## 5. Topic-Level Question Counts on the Discovery Surface
**Observation:**  
[`src/api/v1/subjects.rs`](file:///home/kristency/Projects/utmelab/utmelab-api/src/api/v1/subjects.rs#L112) provides a rich `/syllabus` endpoint with live question counts per topic, but it requires authentication (`SCOPE_READ_CATALOG`). The keyless discovery route (`/api/v1/public/exams`) only reports exam- and subject-level totals (`held` / `verified`).  
**Proposed Solution:**  
Expose topic names and verified question counts on the public catalog. This enables keyless landing pages and viral funnels to display interactive topic pickers (e.g. *"Practice 15 questions on Algebra"* or *"Practice 15 questions on Mechanics"*) before requiring a key.

---

## 6. Paper Assembly with Explanations for Commercial Scoring
**Observation:**  
`POST /api/v1/papers/{exam}/{subject}` deterministically generates complete exam mocks, but answers and explanations are strictly withheld, forcing scoring to go through `.../score`.  
**Proposed Solution:**  
Allow trusted commercial keys (`commercial` tier) to pass `include_explanation=true` on paper assembly. This enables self-hosted test-center servers and offline CBT hubs to grade student papers locally without incurring a network round-trip for scoring.

