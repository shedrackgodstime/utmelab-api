# utmelab-pipeline

Enterprise, modular Python pipeline for automated multi-source question harvesting, mechanical gate validation, AI multimodal verification, and catalog tagging for UTME Lab (JAMB, WAEC, NECO).

This system operates as a fully independent data factory decoupled from the Rust API service (`utmelab-api`). It runs primarily on GitHub Actions workflows and local worker environments, utilizing a **dedicated Turso database** for staging, state management, and queue orchestration.

---

## Architecture & Data Lifecycle

```
                     ┌──────────────────────────────────────────────┐
                     │          Pluggable Harvest Sources           │
                     │  (JAMB archives, WAEC portals, NECO past)    │
                     └──────────────────────┬───────────────────────┘
                                            │
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │         Gate 0: Mechanical Validator         │
                     │  • Stem length & token completeness          │
                     │  • Option count & key validity               │
                     │  • Image/diagram reference check             │
                     │  • SHA-256 fingerprint deduplication         │
                     └──────────────────────┬───────────────────────┘
                                            │ (Valid rows only)
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │         Dedicated Turso Pipeline DB          │
                     │  • Table: `harvest_staging`                  │
                     │  • Status: `harvested` -> `validated`        │
                     └──────────────────────┬───────────────────────┘
                                            │
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │      AI Auto-Tagging & QA Verification       │
                     │    (GitHub Actions Matrix / OpenCode CLI)    │
                     │                                              │
                     │  • Text items: `opencode/space-bunny-free`   │
                     │  • Image items: `muse-spark-1.3-free` via -f │
                     │  • Syllabus pruning & subtopic prediction    │
                     │  • Underline offset snapping & formula check │
                     │  • Answer key validation & explanation triage│
                     └──────────────────────┬───────────────────────┘
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
       [High Confidence & Key Verified]              [Discrepancy / Low Confidence]
                     │                                             │
                     ▼                                             ▼
        Auto-Promotion to Turso Prod               Exception Staging (`review_queue`)
    (`questions` + `verifications` log)              (Triage via CLI / MCP agent)
```

---

## Core Principles

1. **Independent & Modular by Design**:
   Every subpackage (`sources`, `gates`, `ai`, `storage`, `orchestrator`) is strictly decoupled and can be tested and executed independently as a CLI tool or library.
2. **Dedicated Pipeline Database**:
   Harvesting, raw payloads, scraping logs, and intermediate AI evaluations live in a dedicated Turso database. The production database is written to only at the final promotion step.
3. **Single Source of Truth for Catalog**:
   Syllabus topics, subtopics, and official blueprints are read directly from the database at runtime—never hardcoded in stale static JSON files.
4. **Zero-Cost Multimodal AI Execution**:
   Leverages the OpenCode CLI over stdin with zero API costs:
   - Text tasks: `opencode/space-bunny-free`
   - Diagram/Image tasks: `opencode/muse-spark-1.3-contributor-free` using the native `-f /path/to/diagram.png` file context.
5. **High-Throughput Parallelism**:
   Designed for GitHub Actions matrix jobs, dividing subjects across concurrent runners, with internal asynchronous worker pools (`asyncio`).

---

## Project Structure

```text
utmelab-pipeline/
├── README.md                   # System documentation & operational guide
├── pyproject.toml              # Dependencies (libsql-client, pydantic, httpx, click)
├── .github/
│   └── workflows/
│       ├── harvest.yml         # Scheduled / dispatched multi-source crawl
│       └── process_queue.yml   # Distributed matrix AI tagging & QA
├── pipeline/
│   ├── __init__.py
│   ├── config.py               # Turso pipeline credentials, model config
│   ├── storage/                # Dedicated Turso LibSQL client & repository
│   │   ├── __init__.py
│   │   ├── client.py           # Async Turso HTTP client
│   │   ├── schema.py           # DDL for `harvest_staging`, `review_queue`
│   │   └── repository.py       # Query layer for syllabus, staging, and promotions
│   ├── sources/                # Pluggable multi-source harvesters
│   │   ├── __init__.py
│   │   ├── base.py             # Harvester interface & standardized QuestionPayload
│   │   ├── jamb.py             # JAMB past paper crawler
│   │   ├── waec.py             # WAEC portal crawler
│   │   └── neco.py             # NECO scraper
│   ├── gates/                  # Mechanical pre-verification (Gate 0)
│   │   ├── __init__.py
│   │   ├── mechanical.py       # Stem, option, and formatting integrity
│   │   ├── dedupe.py           # Normalized fingerprinting (SHA-256)
│   │   └── media_check.py      # Image reachability & figure detector
│   ├── media/                  # Image & asset manager
│   │   ├── __init__.py
│   │   └── downloader.py       # Caching diagram images for multimodal AI
│   ├── ai/                     # AI engine with OpenCode CLI
│   │   ├── __init__.py
│   │   ├── runner.py           # OpenCode CLI wrapper (stdin + -f image flag)
│   │   ├── prompts.py          # Optimized syllabus pruning & prompt templates
│   │   └── schemas.py          # Pydantic schemas for AI output validation
│   ├── orchestrator/           # Batch runner & promotion engine
│   │   ├── __init__.py
│   │   ├── worker.py           # Async worker pool with bounded concurrency
│   │   └── promoter.py         # Gate 1/2 verification & production sync
│   └── cli.py                  # Operator CLI (`pipeline harvest`, `pipeline run`)
└── tests/                      # Pytest suite with mock providers and schemas
```

---

## Multimodal Image Verification

When a question references a diagram, graph, or music stave:
1. The harvester extracts the image URL.
2. `pipeline/media/downloader.py` downloads and caches the image locally (`.pipeline_cache/media/...`).
3. The AI engine invokes the OpenCode vision model:
   ```bash
   echo "<Question prompt with options>" | opencode run \
     -m opencode/muse-spark-1.3-contributor-free \
     -f .pipeline_cache/media/diagram_123.png
   ```
4. The vision model analyzes the visual evidence alongside the stem, verifies the answer key, and authors/validates the explanation.

---

## Operating Modes

- **Local / Developer Mode**: Inspect single questions, dry-run harvesters, or test AI prompts against staging rows.
- **CI / GitHub Actions Mode**: Headless, matrix-distributed execution across multiple subjects concurrently, writing results straight to the dedicated Turso staging DB and promoting verified rows.
