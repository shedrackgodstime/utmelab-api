# Observed API Limitations & Operational Notes

This document records the technical observations and friction points identified during live testing of the UTME Lab API serving layer.

---

### 1. Mock Scoring Response Payload Sizing
* **Current Behavior**: `POST /api/v1/papers/{exam}/{subject}/score` regenerates and marks the complete 40-question paper. Even when a client submits an answer for only one question, the response includes marking details and full explanations for all 40 questions, with `submitted: null` on the remaining 39.
* **Impact**: The response body reaches approximately 25 KiB. On 2G and 3G networks in Nigeria, this creates unnecessary data overhead and parsing lag when a student or mobile client only needs the aggregate score and status.
* **Suggested Enhancement**: Support a query parameter such as `summary_only=true` or `marked_only=true` so the client receives only the numerical score and items the user actually attempted.

---

### 2. Idle Sync Sleep Waking Latency
* **Current Behavior**: When no traffic arrives for five minutes (`SYNC_IDLE_SECS=300`), the synchronization worker pauses. The first subsequent database read wakes the worker by requesting a locked pull from Turso before fulfilling the request.
* **Impact**: If network latency between the host and Turso spikes during the locked wake-up pull, the incoming request can encounter a brief delay or return a `503 Service Unavailable` (`db_unavailable`) while readiness is momentarily in transit.
* **Suggested Enhancement**: Ensure the existing local SQLite replica continues serving read traffic immediately while the background sync worker handles the cloud catch-up asynchronously.

---

### 3. Sparse Inline Formatting Spans
* **Current Behavior**: The `RichText` model contains an `inline` array that stores formatting markers (subscripts, superscripts, bold, italic, and inline figure anchors) with scalar offsets. Most current questions in the database carry empty `inline: []` lists.
* **Impact**: Chemical formulas (such as H2O or CO2) and mathematical exponents (such as x squared) render as plain text strings unless authors explicitly tag the scalar offsets.
* **Suggested Enhancement**: Expand the ingestion pipeline in `utmelab-bank` to automatically identify, normalize, and tag mathematical exponents, chemical notations, and emphasis markers into scalar offset spans.

---

### 4. Optional Passage Inclusion in Paper Assembly
* **Current Behavior**: `POST /api/v1/papers/{exam}/{subject}` generates questions that reference reading stimuli via `passage_id`, but does not attach the passage object unless the caller explicitly passes `include_passage=true`.
* **Impact**: If a client developer forgets `include_passage=true`, comprehension questions render with missing stimulus texts, forcing the client to make extra round-trip requests to resolve each passage ID.
* **Suggested Enhancement**: Default `include_passage` to true during paper assembly, or bundle a companion passage lookup dictionary directly in the assembled paper payload.

---

### 5. Separation of Key Management and Telemetry
* **Current Behavior**: Detailed runtime health, cache status, and replication metrics live under `/api/internal/admin/*` and require a session cookie rather than a commercial or admin API key.
* **Impact**: Automated monitoring scripts using bearer API credentials cannot inspect detailed synchronization lag without managing dashboard cookie sessions.
* **Suggested Enhancement**: Allow keys carrying administrative scopes (such as `manage:keys`) to read telemetry metrics directly.
