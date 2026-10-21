# UTME Lab Content Pipeline

**Status:** the original brief. **Superseded in part.**
**Date:** 20 October 2026.
**Scope:** the Python content factory that acquires, validates, enriches, and hands over exam content for the serving API.

**Read these first, in this order.**

| Document | What it is |
|---|---|
| `DECISIONS.md` | The sealed decisions. Where this brief and that file disagree, that file wins. |
| `DESIGN.md` | How the bank is supposed to be, derived from the live production database and the live tooling. |
| `HANDOFF.md` | What was measured, what was built, and what is wrong. |

Three things in this brief are settled differently now, and the reasons are
worth reading before the code.

**Promotion is out of scope.** This brief treats the bundle as something the
pipeline promotes. It is not. The bank stops at a ready bundle, and placing
it is separate work.

**The `content_hash` rule below is wrong and has been corrected.** The
production fingerprint does not cover the source identity, the catalog
reference, the passage text or the media. It covers the stem, the option ids
and texts, the answer, the marks, and the explanation. That is the
production algorithm, and the bank's is now byte for byte the same. The
corrected rule is in `DESIGN.md` section 2.7.

**The passage is its own object, not a fragment inside the question.** This
brief nests it. Production has a `passages` table, and 28 questions share 8
passages, so a nested passage cannot be shared and has nowhere to put its
kind.

This document exists to stop the same failure from happening a fourth time. The failure was never Python. It was that the objective lived in prose and in the author's head, while each attempt used a different vocabulary, a different scope, and a different definition of done. Models filled the gaps with confident invention. This file closes the gaps.

If code and this document disagree, stop and fix one of them before writing more code. If a new concept appears in code but not here, it is not allowed to exist.

---

## 1. What the system is

The system is a content factory.

It acquires exam content from sources, adapts it to one canonical model, validates it against reality and against the production catalog, enriches it with model proposals, validates those proposals, and commits a bundle that the serving API can trust.

It is not an agent. It is not a crawler framework. It is not a model gateway. It is not the serving API. Each of those is a separate concern with a separate owner.

The factory has one core sequence and many adapters at the edges. Adding a source or a model must not change the core. That is the whole design test.

---

## 2. How this conclusion was reached

The original prompt was sent to four models with no access to the codebase, so their reasoning would not be shaped by the existing implementation. They converged on the same architecture from four directions:

- A deterministic core, not an agent loop.
- One canonical schema per boundary, validated on entry and exit.
- Sources and AI models are plugins that declare capabilities.
- Several image describers reconcile in a core service, not inside an adapter.
- Validation at three levels: schema, reality, and rules on AI output.
- Build one source, one describer, and one enricher end to end before adding a second of anything.
- Contract tests per plugin, with live smoke tests kept separate.

That consensus is the chassis. The disagreements were about tools, and the current system already settles most of them:

- A workflow server is not needed. The database is already the state and every task is idempotent.
- An ORM is not allowed. The serving API owns the read shapes and the content hash.
- A third-party model gateway is not needed. The repo needs one narrow provider port, not a platform.
- A status column alone is weaker than explicit lanes and validated transitions.

The library choices in section 13 were checked against current sources, not recalled from memory.

---

## 3. Three invariants

Everything below follows from these three rules.

1. **Facts come from sources and reality. Models propose; the core decides.**
   A scraped field, a decoded image, and a catalog row are facts once validated. A model's tag, explanation, or image description is a proposal until the core validates it and commits it.

2. **Every boundary has one canonical schema and one validation law.**
   No dicts crossing boundaries. No ad hoc checks scattered through stages. A stage declares its input, its output, and the law that decides whether it may advance.

3. **The core never names a concrete source, model, transport, or vendor.**
   It asks for a capability. The registry supplies providers. OpenCode, an HTTP API, a vision-only model, and a mock are all the same to the core.

If a change violates one of these, the change is wrong, even if it works.

---

## 4. Vocabulary

The words below are fixed. Future code, tests, and prompts use them with these meanings only.

| Term | Meaning |
|---|---|
| **Source** | An external origin of content, plus the adapter that reads it. It supplies facts. |
| **Source profile** | A source's declaration: name, version, scopes, subject map, capabilities, health. |
| **Source capabilities** | What a source can supply: passages, passage sets, figures, option figures, rich text, answer, explanation, sections, marks. |
| **Provider** | An external origin of judgment, plus the adapter that calls it. It supplies proposals. |
| **Provider profile** | A provider's declaration: modalities, context size, structured output, cost, limits, scorecard. |
| **Capability** | A named operation with a typed request, a typed result, and a validation law. |
| **Proposal** | A model result that has not yet passed the core's validation. |
| **Fact** | A source or reality result that has passed validation. |
| **Task** | One independently runnable unit that advances a bundle by one step. |
| **Goal** | A named sequence of tasks. Composition only. No task calls another. |
| **Bundle** | The unit of content and evidence that moves through the factory and is handed over as one thing. |
| **Catalog snapshot** | A versioned read of the production exam, subject, topic, and subtopic catalog. |
| **Consensus** | A core service that reconciles several proposals for the same capability. |
| **Lane** | A storage area that reflects lifecycle state. A task with a wrong selector cannot reach a later lane. |
| **Scorecard** | A measured accuracy record for a provider on a capability. Confidence is not a scorecard. |

Two words are often confused and must not be:

- A **source** answers "where did this content come from?"
- A **provider** answers "who produced this judgment?"

They share a plugin shape. They do not share trust.

---

## 5. Layers and the dependency rule

Four layers, one direction of dependency.

```text
interface        CLI, config, workflows
    |
application      tasks, goals, consensus, orchestration
    |
domain           models, capabilities, ports, state machine, policies
    ^
adapters         sources, providers, media, catalog, store
```

Rules:

- `domain` imports nothing from `httpx`, any model SDK, any SQL client, or the CLI.
- `application` imports `domain` only. It receives adapters through ports.
- `adapters` import `domain` and their own external library. They never import each other.
- `interface` wires everything and contains no business rule.
- A module in `domain` that imports `httpx` is already a design failure.

This is the same separation used by production data aggregators: domain, adapters, infrastructure, and schemas. It is what makes each layer testable in milliseconds and runnable without the rest.

---

## 6. Source contract

A source is a plugin with a profile and four operations.

```python
class Source(Protocol):
    profile: SourceProfile

    async def probe(self, scope: Scope) -> Coverage:
        """Report what exists for a scope without writing rows."""

    def fetch(self, scope: Scope) -> AsyncIterator[SourceItem]:
        """Yield source items with raw payload and provenance. May be an async generator."""

    def adapt(self, item: SourceItem, catalog: CatalogSnapshot) -> RawBundle:
        """Map one source item into the canonical bundle shape."""

    def validate(self, item: SourceItem) -> list[Issue]:
        """Report source-level problems before adaptation."""
```

`SourceItem` keeps the raw payload, the source URL, the source item id, the fetch time, the scope, the source version, and the payload hash. Adaptation never invents a field the source did not supply.

`adapt` returns a `RawBundle`: canonical content plus `MediaRef` entries that name media by a source-local key. The media task fetches each ref, hashes the bytes, and produces a `MediaAsset`. The final `Bundle` carries assets, evidence, state, and hashes.

`SourceProfile` declares what the source can provide. The core uses that declaration to decide what is required. It does not infer requirements from the wording of a question stem.

```python
class SourceCapabilities(BaseModel):
    passages: bool = False
    passage_sets: bool = False
    figures: bool = False
    option_figures: bool = False
    rich_text: bool = False
    answer: bool = True
    explanation: bool = False
    sections: bool = False
    marks: bool = False
```

One source may cover several exams. JAMB, WAEC, and NECO on the same site are scopes of one source, not three sources. A genuinely different origin is a second source. That distinction keeps the registry honest.

---

## 7. Provider contract

A provider declares a profile and implements the capability protocols it supports. It does not implement the ones it does not support.

```python
class DescribeImage(Protocol):
    async def describe_image(self, req: ImageRequest) -> ImageDescription:
        ...

class Explain(Protocol):
    async def explain(self, req: ExplainRequest) -> Explanation:
        ...

class Tag(Protocol):
    async def tag(self, req: TagRequest) -> TagSet:
        ...

class VerifyAnswer(Protocol):
    async def verify_answer(self, req: VerifyRequest) -> AnswerVerdict:
        ...
```

No `NotImplementedError` in the core. A provider that cannot describe images is never asked to. The registry maps capability to the providers that implement it.

```python
class ProviderProfile(BaseModel):
    name: str
    model: str
    modalities: set[Literal["text", "image"]]
    structured_output: bool
    context_tokens: int | None
    cost_note: str
    limits_note: str
    scorecard: Scorecard | None = None
```

Provider selection is configuration and policy, not a hardcoded branch. A capability may have one preferred provider, several for consensus, or a minimum scorecard.

---

## 8. Capability contracts and validation laws

Each capability owns an input model, an output model, and a validation law. This is the "each process has its own validation" requirement, made explicit.

Example: `describe_image`.

- **Input:** a stored asset with a content hash, MIME type, and dimensions.
- **Output:** a description, a list of quoted visual facts, a confidence, and the provider id.
- **Law:** the asset must decode; the description must be non-empty; quoted facts must refer to the asset; confidence must be in range; the output must validate against the schema.

Example: `tag`.

- **Input:** a bundle and a catalog snapshot.
- **Output:** one topic id, one subtopic id, evidence text, and a confidence.
- **Law:** the subtopic must exist in the snapshot; the evidence must appear in the stem or passage; no invented slug is accepted.

Example: `explain`.

- **Input:** a validated bundle plus any image description.
- **Output:** a structured explanation with key point, body, and distractor trap.
- **Law:** required sections present; no new facts about the answer; length and language rules; the explanation must not contradict the recorded answer.

Three validation levels apply everywhere:

1. **Schema.** Pydantic rejects the wrong shape.
2. **Reality.** The URL resolves, the bytes decode, the file is an image, the catalog row exists.
3. **Policy.** The result is acceptable for this bundle and this trust level.

A failure produces a typed rejection with a reason. Nothing passes silently.

---

## 9. The pipeline and the state machine

The database is the queue. A task reads rows in one state, performs one job, validates, and writes the next state. Re-running is safe because the keys are stable.

The canonical sequence:

```text
planned -> acquired -> adapted -> gated -> deduped -> catalogued
        -> media_ready -> described -> enriched -> verified -> ready
```

Terminal states: `rejected` and `failed`.

Branches:

- No media: `catalogued` goes directly to `enriched`.
- Required media missing or unreadable: `rejected`, with a reason.
- A required capability has no qualified provider: `failed`, not guessed.

Each task is runnable alone:

```text
pipeline acquire --source <name> --scope <exam/subject/year>
pipeline adapt   --where 'state=acquired'
pipeline gate    --where 'state=adapted'
pipeline media   --where 'state=catalogued and has figures'
pipeline describe --where 'state=media_ready'
pipeline enrich  --where 'state=described or state=catalogued'
pipeline verify  --where 'state=enriched'
pipeline ready   --where 'state=verified'   # hands the bundle over
```

The state machine is defined once and validates that no transition is invented. A task declares the state it consumes and the state it produces. A selector is data and cannot cross a lane boundary.

---

## 10. The bundle

The serving API does not read a row. It reads a bundle. The bundle is the unit that moves, is verified, and is handed over.

```text
Bundle
  source:
    provider, source_url, source_item_id, fetched_at, payload_hash, source_version, scope
  catalog:
    exam, subject, year, section, topic_id, subtopic_id, catalog_version
  content:
    stem, options, answer, inline marks, source explanation
  passage:
    id, exam, subject, year, kind, title, author, text
    a question names a passage by id, never by nesting it
  media:
    validated assets, each addressed by its sha256
  evidence:
    gate verdicts, media descriptions, model proposals, verification records
  state:
    state, attempts, errors
  hashes:
    payload_hash, content_hash, bundle_hash
```

Rules:

- `payload_hash` covers the raw source payload. It detects upstream drift.
- `content_hash` is the production fingerprint, and it covers the facts the
  served row is made of: the stem text, each option's id and text, the
  answer, the marks on the stem and the options, and the explanation's key
  point, body and trap. It does **not** cover the source identity, the
  catalog reference, the passage text, the media, the section or the
  difficulty. The rule above, which claimed otherwise, was wrong and is
  corrected here.
- `bundle_hash` covers `content_hash` plus the catalog version. It excludes model proposals and timestamps, so the same facts and catalog snapshot produce the same hash.
- Evidence is stored with the bundle and referenced by the content hash. Evidence never changes the bundle hash.
- A bundle is handed over whole. It never carries a question without its passage link, media link, and deciding verification.
- Provenance is carried, not replaced by a generic source label.
- The catalog version is stored so a later catalog change can be detected.

This is why the bundle exists. A row-oriented pipeline can report success while the serving predicate returns false. The bundle makes that impossible to miss.

---

## 11. Media as evidence

An image URL is not evidence. The pipeline treats media as a first-class asset.

1. Discover the asset from the source payload.
2. Fetch it with `httpx`, with a size limit and timeout.
3. Hash the bytes.
4. Sniff the magic bytes and confirm the MIME type.
5. Decode it to confirm it is a real image and read its dimensions.
6. Store the bytes and record the hash, MIME, dimensions, source URL, and fetch time.
7. If the source declares that a figure is required, mark the asset required.
8. Pass the stored asset to every qualified `describe_image` provider.
9. Store each description with its provider, confidence, and quoted facts.
10. Reconcile descriptions in the consensus service.
11. Block promotion if required media is missing or unreadable.

The `required` flag comes from the source profile and the adapted bundle, not from guessing that the stem says "the diagram above". Wording is not data.

---

## 12. Trust and verification

A model verdict is a proposal. It never claims to be a human review.

A bundle becomes servable only when the policy the serving API enforces is satisfied. If that policy requires a human pass over the answer and the explanation, only a human record counts, and only the latest record decides. A model pass is signal, not authority.

Changing that is a product and API decision. It requires a measured scorecard with an acceptable precision threshold and an explicit API contract change. It is not a configuration flag, and it is not achieved by relabeling an AI row as human.

This rule protects the product. It also protects the pipeline from the temptation to move rows quickly into a place where they are not served.

---

## 13. Library decisions

The goal is a thin codebase. Every dependency below earns its place. Tools that add a server, a second source of truth, or an abstraction we do not need are rejected.

### 13.1 Runtime picks

| Layer | Pick | Why | Rejected |
|---|---|---|---|
| Schemas and settings | `pydantic` v2, `pydantic-settings` | One validated shape per boundary; structured AI output; typed env config. | dict passing, hand checks |
| Plugins | stdlib `importlib.metadata.entry_points` plus a `Protocol` and a decorator registry | Official PyPA discovery. A plugin installed as a package is found without editing core. First-party plugins register on import. | hardcoded factory trees, `pluggy` |
| HTTP | `httpx` | Async, HTTP/2, one client for scraping and media. | `requests`, `aiohttp` |
| Retries | `stamina` | Opinionated tenacity wrapper: safe defaults, async, type hints, global disable in tests, structured logging hooks. | hand-rolled backoff |
| Rate limit | `aiolimiter` | Leaky bucket with a real async contract, matching per-provider limits. | sleeps, unbounded fan-out |
| HTML | `selectolax`, fallback `lxml` | Fastest correct parser in current benchmarks, releases the GIL, runs in threads. `lxml` when XPath is required. | BeautifulSoup default, regex |
| Image sniff | `filetype` | Pure Python, no C library, reads magic bytes. | extension checks, `python-magic` on Termux |
| Image decode | `Pillow` | Confirms the bytes decode, gives dimensions, catches corruption. | trusting Content-Type |
| Database | `pyturso` locally, `libsql` or `turso_serverless` remotely | The serving API owns the schema. `pyturso` is the current local driver, sqlite3-compatible and MVCC. No ORM. | SQLAlchemy, Alembic |
| State | `python-statemachine` | Declarative StateChart, validates unreachable and trap states at class definition, async aware, Mermaid diagrams. | status strings, scattered if/else |
| Structured output | Pydantic at the seam; `Instructor` optional inside API adapters | Instructor gives `response_model` plus retry-on-validation across many providers. It stays inside the adapter. | Pydantic AI, LiteLLM proxy |
| CLI | `Cyclopts`, fallback `Typer` | Type hints and docstrings become args and help; parses dataclasses and Pydantic models; minimal boilerplate. | argparse boilerplate |
| Logs | `structlog` | Flat JSON by default, one processor chain, `contextvars` for run id, captures stdlib logs. | `print`, Loguru in production |
| Tests | `pytest`, `pytest-asyncio` auto, `respx`, `hypothesis`, `pytest-cov` | respx mocks at the httpx transport so requests are real up to the boundary. Hypothesis for validators and hashes. | patching clients |

The state table stays the single source of truth. `python-statemachine` is a wrapper option for guards and generated diagrams, not a second copy of the transitions.

Sources: [entry points](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/), [stamina](https://stamina.hynek.me/en/stable/), [aiolimiter](https://github.com/mjpieters/aiolimiter), [HTML parser benchmarks](https://webscraping.cc/blog/html-parser/), [filetype](https://github.com/h2non/filetype.py), [Turso Python SDK](https://docs.turso.tech/sdk/python/reference), [python-statemachine](https://python-statemachine.readthedocs.io/en/stable/how-to/coming_from_transitions.html), [Instructor vs LiteLLM](https://faun.dev/toolbox/instructor-vs-litellm/), [Cyclopts](https://mrkeyoor.com/libs/cyclopts/), [structlog](https://www.structlog.org/), [respx](https://lundberg.github.io/respx/), [pytest-asyncio modes](https://pytest-asyncio.readthedocs.io/en/stable/concepts.html).

### 13.2 What we do not add

- **Prefect, Dagster, Temporal, Airflow.** They add a server or control plane. The database is already the state, tasks are idempotent, and a crash is repaired by retrying the row.
- **DBOS, Hatchet, Restate.** Good tools, but they require Postgres or a server. We do not have cross-machine durability or multi-tenant queues.
- **Celery and Redis.** A second queue beside the database.
- **SQLAlchemy and Alembic.** The serving API owns the schema. An ORM would duplicate and drift from the contract.
- **LiteLLM proxy.** A server on the critical path of every model call.
- **LangChain and Pydantic AI.** Agent frameworks when the steps are fixed.
- **`python-magic`.** It needs libmagic, which is friction on Termux and in slim images.
- **`pluggy`.** Built for hook-based hosts. We need capability lookup, not hooks.
- **BeautifulSoup as a default.** Acceptable for throwaway scripts, not for the pipeline.

### 13.3 OpenCode

OpenCode is one provider adapter, not the architecture.

- It lives in `adapters/providers/opencode/`.
- Its transport details stay there: subprocess, stdin prompt, image flag, JSON event parsing, timeout, retries, raw response capture.
- It declares the capabilities it supports, for example `tag`, `explain`, and `describe_image`.
- Its output is a proposal. The core validates it.
- It is never used as the orchestrator. The pipeline does not let a model choose steps.
- Replacing it with an HTTP provider changes configuration, not core.
- The free tier is a deployment detail, not a dependency. If it disappears, another adapter takes its place.

An API provider follows the same pattern with a different transport. A vision-only provider implements `describe_image` and nothing else. That is what "adapt each provider to our needs" means in practice: local adapter work, no core edits.

---

## 14. Repository shape

```text
src/utmelab_bank/
  domain/
    models/          canonical bundle, source item, proposals, verdicts
    capabilities.py  capability names and typed requests
    enums.py         the fixed vocabulary
    gate.py          the rules, pure, no I/O
    hashing.py       the content fingerprint
    ports.py         Source, DescribeImage, Explain, Tag, Catalog, MediaStore, ContentStore
    state.py         transition table, guards, terminal states
    selector.py      typed query data for lanes and scopes
  adapters/
    sources/         one package per source
    providers/       one package per provider
    media/           fetch, sniff, decode, store, describe, reconcile
    catalog/         versioned production reference reader
    store/           the bank's tables and their migrations
    gate_service.py  runs the gate over a staging item
  config.py
tests/
  fixtures/          recorded source payloads
  contract/          one contract suite per source and provider
  live/              the contracts that hit the real database and a real model
```

The application and interface layers this brief describes are not built.
There is no CLI and no task runner yet, so everything is driven from Python.
What they should be is settled in `DECISIONS.md`.

No task imports another task. No adapter imports another adapter. No domain module imports an infrastructure library or names a concrete adapter. Pydantic is the one allowed schema dependency.

---

## 15. Testing strategy

Each layer has one kind of proof.

- **Domain unit tests.** No network, no database. State transitions, policies, consensus, hash rules, selector rules. Run in milliseconds.
- **Adapter contract tests.** A recorded source payload must adapt to a valid bundle with the expected provenance, passage, marks, and media. A recorded provider reply must validate to the expected proposal. One suite per adapter.
- **Transport tests.** `respx` intercepts httpx at the transport. The real request is built and can be asserted. Retries are tested with a scripted failure then success.
- **Property tests.** Image sniffing, offset snapping, hash stability, and bundle round-trips with `hypothesis`.
- **Live smoke tests.** Small, explicit, run separately. They catch upstream drift and outages. They never run in the fast suite.
- **Acceptance tests.** One per state transition, plus one that applies the serving predicate to a ready bundle and expects true. A green unit suite with a red serving predicate is not a pass.

Every task must be runnable alone in a test. If a task needs the whole pipeline, its boundary is wrong.

---

## 16. Build order

Do not build the whole pipeline at once. Each step below is independently shippable and testable.

1. **Write this document and the vocabulary.** No code.
2. **Define the canonical models, capability names, and ports.** No implementations.
3. **Implement the state machine and the selectors.** Prove that invalid transitions are rejected.
4. **Implement one source adapter with fixtures.** Prove `probe`, `fetch`, `adapt`, and `validate`.
5. **Implement the mock provider and the OpenCode adapter.** Prove that the core sees only the port.
6. **Run one capability end to end.** Use `describe_image` first, because it forces media to be real.
7. **Add the consensus service.** Prove it with mock providers that disagree.
8. **Add `tag` and `explain` as separate capabilities.** Do not bundle them into one call.
9. **Add a second provider with a different capability set.** This is the real proof of the capability port.
10. **Add a second source that is not a copy of the first.** This is the real proof of the source port.
11. **Add persistence and bundle promotion in one transaction.**
12. **Add the trust policy and the serving predicate check.**
13. **Add scorecards and measured provider selection.** Only then consider relaxing human review.

If step 9 requires a core edit, the provider abstraction is wrong. Fix it before adding more providers.

---

## 17. Definition of done

The architecture is done when these are true:

- Adding a source touches only `adapters/sources/<name>`, one registry entry, and fixtures.
- Adding a provider touches only `adapters/providers/<name>`, its capability declarations, and configuration.
- Every task runs alone from the CLI against a selector.
- Every boundary fails closed with a named error and a reason.
- The same input and the same catalog snapshot produce the same bundle hash.
- A bundle is handed over whole, never a question on its own.
- The serving predicate accepts every ready bundle, and the pipeline refuses to mark a bundle ready when it would not.
- A model cannot write to the store, choose a pipeline step, or claim a human verification.
- The fast test suite needs no network and no live database.

---

## 18. Open decisions

These are the remaining choices that need a human answer before or during the first milestone. They are deliberately not guessed in code.

1. **Package name and Python version.** Recommended: Python 3.12 or newer, because current pure-Python image and parser libraries target it.
2. **The first source and its capabilities.** The source profile must be written before its adapter.
3. **The first capability.** Recommended: `describe_image`, because it exposes media truth early.
4. **The serving trust policy.** Human pass only, or a measured AI policy later. The default must match what the API actually enforces.
5. **Media storage target.** Local, a git-backed store, or object storage. The adapter hides the choice.
6. **Provider scorecard thresholds.** Required before any AI verdict can replace human review.
7. **The catalog snapshot interface.** How version and hash are read from the serving database.

---

## 19. The conclusion

The system succeeds when it is boring to read. The core sequence should look like a table of contents: acquire, adapt, gate, dedupe, catalogue, describe, enrich, verify, hand over. All the mess lives behind ports.

Sources supply facts. Providers supply proposals. The core supplies certainty. The bundle carries the evidence, and the trust policy decides what may be served.

OpenCode is the first provider because it is free and capable. It is not the foundation. The foundation is the capability port, the canonical schema, and the validation law. With those in place, any provider, any source, and any transport can be added without touching the core.

The earlier failures were not caused by a weak model. They were caused by an under-specified objective and a scope that grew faster than the contracts. The correction is this document, one task at a time, and tests that prove the serving predicate, not merely the unit.

That is the conclusion. Build the smallest path that satisfies it, then earn the second source, the second provider, and the second capability.
