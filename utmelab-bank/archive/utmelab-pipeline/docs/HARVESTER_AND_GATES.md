# Harvesters & Gate 0 Mechanical Validation — utmelab-pipeline

**Parent System:** UTME Lab Pipeline  
**Module:** `pipeline.sources` & `pipeline.gates`  
**Specification Date:** 2026-10-14

---

## 1. Pluggable Harvester Architecture

The pipeline supports diverse external sources. Each source crawler implements a uniform abstract interface:

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator
from pydantic import BaseModel
from typing import List, Optional

class RawOption(BaseModel):
    id: str           # "a", "b", "c", "d", "e"
    text: str

class RawQuestionPayload(BaseModel):
    source_name: str         # e.g., "jamb_cbt_archive_v1"
    source_url: str
    source_item_id: str      # Source's remote unique ID
    exam: str                # "JAMB" | "WAEC" | "NECO"
    subject: str             # Canonical slug e.g. "mathematics"
    year: int                # Cohort year e.g. 2025
    stem: str                # Raw unformatted stem
    options: List[RawOption] # List of raw options
    reported_answer: str     # Reported answer key e.g. "b"
    reported_explanation: Optional[str] = None
    media_url: Optional[str] = None
    section: Optional[str] = None
    passage_text: Optional[str] = None

class BaseHarvester(ABC):
    """Abstract base class for all source harvesters."""
    
    @property
    @abstractmethod
    def source_name(self) -> str:
        pass

    @abstractmethod
    async def crawl(
        self,
        subject: str,
        year: Optional[int] = None,
        limit: Optional[int] = None
    ) -> AsyncIterator[RawQuestionPayload]:
        """Yields raw question payloads one by one."""
        pass
```

---

## 2. Gate 0 Mechanical Checks (Zero Token Cost)

Before any question is recorded in `harvest_staging` or sent to the AI engine, it must pass **Gate 0**. If any check fails, the question is rejected with a specific mechanical defect reason.

### The 5 Gate 0 Invariants

| Check | Condition | Failure Reason |
|---|---|---|
| **1. Stem Sanity** | Stem is not null, `len(stem.strip()) >= 10`, does not end prematurely with trailing punctuation like `...` without explanation | `stem_too_short` or `stem_malformed` |
| **2. Option Counts & Keys** | **JAMB**: Exactly 4 options (`a`, `b`, `c`, `d`).<br>**WAEC/NECO**: 4 or 5 options (`a`, `b`, `c`, `d`, `e`).<br>All option texts must be non-empty and keys must be unique. | `invalid_option_count` or `empty_option_text` |
| **3. Answer Key Validity** | The reported answer must be a single character matching one of the option IDs (`a` through `e`). It cannot be a number, index, or full text. | `invalid_answer_key` |
| **4. Diagram / Figure Reference** | If the stem contains regex matches for figure keywords (`diagram (above|below)`, `figure \d+`, `stave above`, `chart below`), `media_url` **must** be provided and return HTTP `200 OK` with an image MIME type. | `missing_referenced_figure` or `broken_media_url` |
| **5. SHA-256 Deduplication** | The normalized stem fingerprint must not already exist in `harvest_staging.fingerprint` or the production `questions.content_hash`. | `duplicate_stem` |

---

## 3. Crawl Politeness & Resilience

All harvesters inherit polite network behaviors:
1. **Single-Worker Sequential Pacing**:
   Default delay of `1.5s - 2.5s` between consecutive requests to external servers.
2. **Transparent User-Agent**:
   Identifies requests clearly (e.g. `User-Agent: UTMELab-Harvester/2.0 (+https://utmelab.com/bot)`).
3. **Exponential Backoff**:
   Retries with exponential jitter on HTTP `429` (Too Many Requests) and `5xx` errors, with a maximum of 3 retries before logging a warning and proceeding.
