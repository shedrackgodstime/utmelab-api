# Zero-Latency Serving & Local-First Architecture Proposal

**Date:** 2026-11-17  
**Status:** Accepted / Implementation Stage  
**Target:** Elimination of cold-start stalls, zero-wait read serving, offline mock test execution, and edge acceleration.

---

## 1. Problem Statement

Under the previous model, client requests frequently encounter high tail latency or apparent service unresponsiveness (10+ second delays) due to:

1. **Synchronous Wake Pulls**: When the replica sleeps after 5 idle minutes, the first incoming read request halts on `wake_if_sleeping` while awaiting a 30-second network pull from Turso cloud.
2. **Gate Permitting Deadlock**: Concurrent requests hoard `DbGate` permits while waiting behind `write_mutex` during network pulls, rejecting excess callers with HTTP 503 (`DbSaturated`).
3. **No Immediate Client Retry Guidance**: HTTP 503 and 408 responses lack `Retry-After` headers, leaving standard browser `fetch()` callers to fail abruptly.
4. **Network Dropouts During CBT**: High-stakes examination practice (UTME / WAEC / NECO) on mobile cellular connections fails when network sockets drop during active mock tests.

---

## 2. Architecture Pillars

```
                     ┌────────────────────────────────────────┐
                     │           Client Application           │
                     │  - Hedged requests (1.2s trigger)      │
                     │  - Local CBT Engine (IndexedDB/OPFS)   │
                     │  - Transparent retry with backoff      │
                     └───────────────────┬────────────────────┘
                                         │
                         HTTPS Request   │ (Fast path)
                                         ▼
                     ┌────────────────────────────────────────┐
                     │          Edge CDN Cache Layer          │
                     │  - Keyed to x-bank-version             │
                     │  - Stale-while-revalidate              │
                     └───────────────────┬────────────────────┘
                                         │ Cache miss (2-5%)
                                         ▼
                     ┌────────────────────────────────────────┐
                     │              API Server                │
                     │  - Non-blocking SWR wake-up            │
                     │  - Gate permit acquired after db ready │
                     │  - Retry-After emitted on 503/408      │
                     └───────────────────┬────────────────────┘
                                         │
                                         ▼
                     ┌────────────────────────────────────────┐
                     │     Local SQLite Replica (Disk)        │
                     │  - Read latency: 1-3ms                 │
                     │  - Background async cloud sync worker  │
                     └────────────────────────────────────────┘
```

---

## 3. Implementation Phases

### Phase 1: Server-Side Non-Blocking Read Serving (Immediate)
* **Decouple Wake Pulls from Reads**: Modify `wake_if_sleeping` so that existing, verified local replicas answer reads instantly. Trigger the cloud synchronization catch-up out-of-band in the background.
* **Permit Re-ordering**: Acquire `DbGate` semaphore permits only after ensuring the database handle is accessible.
* **Standard Retry Headers**: Emit `Retry-After: 1` on `DbSaturated` and `DbContended`, and `Retry-After: 2` on `RequestTimeout`.
* **Fix Point Queries**: Rewrite `get_book` in `src/store/chapters.rs` to run `WHERE id = ?1 LIMIT 1` instead of scanning all records in memory.

### Phase 2: Schema Hardening & Foreign Key Indexes
* Apply Migration 11 in `src/store/schema.rs` to add covering indexes on `chapter_exercises(chapter_id)`, `exam_traps(chapter_id, section_id)`, and `exam_recall_checks(chapter_id, section_id)`.
* Enforce pagination and limits on `list_traps` and `list_recall_checks`.
* Convert `import_chapter` into atomic statement batches using `execute_write_batch`.

### Phase 3: Client Resilience & Request Hedging
* Deploy a shared HTTP client utility that applies request hedging: if a read request takes longer than 1.2 seconds, dispatch an identical parallel request.
* Implement automatic, bounded exponential backoff for transient 503 and 408 responses honoring `Retry-After`.

### Phase 4: Offline-First CBT Engine
* Package assembled 40-question mock exams into self-contained bundles stored in browser IndexedDB.
* Run navigation, timers, and scoring locally on the client without runtime network dependency.
* Sync scores and report telemetry to the server asynchronously upon test completion.
