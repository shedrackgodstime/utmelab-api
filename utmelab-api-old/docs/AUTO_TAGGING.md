# Auto-tagging (prototype) — workflow + SDK

**Status:** working prototype, proven end-to-end on GitHub Actions (2026-10-14).
Prints proposals only — it never writes to the bank.

## What it is

A dispatchable GitHub Actions workflow plus a small Python SDK that reads the
question bank (or the WAEC bank), asks a **free** LLM backend to tag each
question, and uploads the result as a **downloadable artifact** (the repo is
never written to). For each question it proposes:

- **subtopic** — the single best subtopic slug from the syllabus;
- **underline** — the underlined word/phrase, with a stem offset;
- **answer check** — whether the recorded answer is correct;
- **explanation quality** — `GOOD` / `PARTIAL` / `POOR` / `MISSING`.

## Why it is free

It runs `opencode run` with an OpenCode Zen **free** model
(`opencode/space-bunny-free`) from *inside* the client. The Zen chat endpoint
rejects direct HTTP callers (`FreeTierError`), so the CLI is the seam: no API
key, no per-IP limit. The prompt is fed via **stdin** — passing it as an argv
positional breaks on stems containing tokens like `-3x` (yargs reads them as
flags).

## How it works

```
workflow_dispatch ─▶ install opencode CLI ─▶ tools/auto_tag_questions.py (shim)
                                               └─▶ utmetag SDK
                                                     ├─ bank.py    load/filter questions + syllabus
                                                     ├─ prompt.py  build the tagging prompt
                                                     ├─ providers/ the swappable model backend
                                                     ├─ tasks.py   parse + validate + snap offsets
                                                     └─ runner.py  bounded-concurrency run
                                            ─▶ tagging_results.json ─▶ upload-artifact
```

The design point is the **`Provider` seam** (`tools/utmetag/providers/base.py`):
one method, `async complete(prompt) -> str`. The task and runner layers never
import a concrete backend, so the model backend is swappable. There are exactly
two engines, and only one talks to a model:

| Engine | Backend | Notes |
|---|---|---|
| `opencode` (default) | `opencode run` CLI | free Zen models; no key. **The only model backend.** |
| `mock` | in-process | no network; deterministic; tests only |

OpenCode is the sole model provider by design — the flow never falls back to a
paid API (there is no OpenAI/Pollinations path). "Free" is a requirement, not a
default.

The prompt embeds the question stem, options, recorded answer, explanation, and
the **syllabus** for that subject: `AVAILABLE SUBTOPICS` (`slug: name (topic: …)`
plus an indented `objectives:` line when present) and `AVAILABLE TOPICS`. JAMB
topics carry objectives (582/582); WAEC currently has none. The model must reply
with JSON only; replies are parsed tolerantly (fences/prose) and validated with
pydantic, and a wrong underline offset is snapped to the word's real position.

## How to run it

**GitHub (preferred):** Actions → **Auto-tag Questions Prototype** → *Run workflow*.
Inputs: `subject`, `data_dir` (`data` or `data/waec`), `exam` (`JAMB`/`WAEC`),
`limit`, `engine`, `model`, `include_verified`. Output is the artifact
`auto-tag-results-<subject>-<run>` (7-day retention).

**Local:**

```bash
# offline smoke
python3 tools/auto_tag_questions.py --engine mock --subject mathematics --limit 5 --all

# free real model against the WAEC bank
python3 tools/auto_tag_questions.py --engine opencode --data-dir data/waec \
    --exam WAEC --subject computer-studies --limit 49

# SDK tests (no network)
python3 -m pytest tools/utmetag/tests -q      # 79 tests
```

## What we ran (2026-10-14)

| Run | Bank / subject | Result |
|---|---|---|
| [38604464872](https://github.com/shedrackgodstime/utmelab-api/actions/runs/38604464872) | WAEC `computer-studies`, 49 q | 49/49 success, 44 subtopics assigned (all valid slugs), 45/49 answers ok, 0 underlines, 120s |
| [38606089842](https://github.com/shedrackgodstime/utmelab-api/actions/runs/38606089842) | JAMB `mathematics`, 20 q (`--all`) | 20/20 success, 19 subtopics all valid, 20/20 answers verified, 77s |

Notable findings:

- **Zero hallucinated subtopics** across both runs (44/44 and 19/19 were real
  syllabus slugs).
- The WAEC run caught **two genuine answer-key errors** (HTTP expansion; Slide
  Rule vs ENIAC for "did not exist before the 19th century") and correctly
  refused two questions whose "Table 3" was not present in the data.
- On JAMB mathematics, **14/20 exactly matched the existing `subtopic_id`**; the
  misses clustered on indices/logarithm items all collapsing onto the broad
  `relationship-between-indices-and-logarithm` subtopic (over-generalization).

## What it can help with

- **Pre-labelling the untagged backlog.** 211 JAMB questions have no
  `subtopic_id` (60 of them also unverified); **all 396** WAEC questions are
  untagged. A run turns a whole subject into candidate tags for a human to
  accept.
- **Answer-key QA.** It flags recorded answers the model believes are wrong —
  it already surfaced two real defects.
- **Explanation triage.** Ranks which questions need an explanation written or
  rewritten.
- **Underline repair.** Locates the underlined word and its offset.
- **Review prioritisation.** Sort proposals by `confidence` and send the
  low-confidence ones to a human first.

## Limits and cautions

- **AI signal only, never verification.** Under decision **D62**, `verified` is
  derived from the human verification log; AI rows are signal only. Nothing here
  may assert a human review, so output is proposals for `tools/review.py`, not a
  write.
- **No write-back.** The workflow emits an artifact; it does not touch the bank
  or the DB.
- **Over-generalization** on some closely-related subtopics (see indices/log
  pattern above).
- **External references** (tables, figures, passages not in the stem) cannot be
  verified and come back low-confidence.
- **Speed.** Roughly 3-5 s/question at concurrency 3 on the free model; a
  49-question subject took ~2 minutes.

## Relationship to the MCP surface

The SDK was deliberately shaped so the **data layer** is swappable the same way
the model backend is: `bank.py` could gain an `McpBankSource` alongside the
current JSON loader, and write-back would become an `McpBankSource` tool call.
The repo already reserves `src/mcp/` for this (see `src/mcp/README.md`), but that
surface is an empty scaffold: auth and "what AI may write" are undecided, and
must land in `docs/QUESTION_BANK_DECISIONS.md` before any code (D7/D62).
