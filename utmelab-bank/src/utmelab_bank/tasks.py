"""The task runner. Each step is one independent unit of work.

A task lists the rows it can act on, does one thing to each, and reports what
happened. It does not call the next task. The presets are just named lists of
tasks, run in order, so a scrape can stop at deduped and a later run can pick
up the media and the catalogue without the source being alive.

The runner is deliberately boring. The state machine decides what is legal;
the services decide what is correct; a task only moves rows between them and
records the result. That is what makes a failed row stay visible instead of
disappearing into a batch total.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from utmelab_bank.adapters.gate_service import GateService
from utmelab_bank.adapters.providers.tagging import ExplainService, TagService
from utmelab_bank.adapters.ready_service import ReadyService
from utmelab_bank.adapters.review_service import ReviewService
from utmelab_bank.adapters.store.index import BANK, BATCH, PRODUCTION
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import Scope, StagingItem
from utmelab_bank.runtime import Runtime, require

logger = logging.getLogger(__name__)

#: How many rows a batch task takes when the caller does not say.
DEFAULT_LIMIT = 100


class UsageError(RuntimeError):
    """The command was asked to do something it cannot do as written."""


@dataclass(frozen=True)
class TaskOptions:
    """What the caller told the task about the batch."""

    exam: str | None = None
    subject: str | None = None
    year: int | None = None
    section: str | None = None
    limit: int | None = None
    dry_run: bool = False


@dataclass
class TaskResult:
    """What one task did, in a form both a person and a workflow can read."""

    task: str
    seen: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    blocked: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether the task finished without a failure or a blocked row."""
        return self.failed == 0 and self.blocked == 0

    def fail(self, message: str) -> None:
        """A row or a step raised, and someone has to look at it."""
        self.failed += 1
        self.errors.append(message)

    def block(self, message: str) -> None:
        """A row was refused by the bank's own rules, not by a crash."""
        self.blocked += 1
        self.notes.append(message)

    def note(self, message: str) -> None:
        """Something the operator should know, without changing the count."""
        self.notes.append(message)

    def as_dict(self) -> dict[str, object]:
        """The result as plain data, for ``--json`` and a workflow step."""
        return {
            "task": self.task,
            "seen": self.seen,
            "done": self.done,
            "skipped": self.skipped,
            "failed": self.failed,
            "blocked": self.blocked,
            "errors": list(self.errors),
            "notes": list(self.notes),
        }


def summary(result: TaskResult) -> str:
    """One line a person can scan at the end of a run."""
    return (
        f"seen={result.seen} done={result.done} skipped={result.skipped} "
        f"failed={result.failed} blocked={result.blocked}"
    )


TaskFn = Callable[[Runtime, TaskOptions], Awaitable[TaskResult]]


def _scope(options: TaskOptions) -> Scope:
    """The source scope, which the scrape must name in full."""
    if not options.exam or not options.subject or options.year is None:
        raise UsageError("this command needs --exam, --subject and --year")
    return Scope(
        exam=options.exam,
        subject=options.subject,
        year=options.year,
        section=options.section,
    )


def _limit(options: TaskOptions) -> int:
    """The batch cap, with the default applied and a nonsense value refused."""
    limit = DEFAULT_LIMIT if options.limit is None else options.limit
    if limit <= 0:
        raise UsageError("--limit must be positive")
    return limit


async def _rows(
    runtime: Runtime,
    states: tuple[State, ...],
    options: TaskOptions,
) -> tuple[StagingItem, ...]:
    """Read the rows a task can act on, within the optional scope filter.

    The section is filtered here rather than in the query because the staging
    table has no section index and a section is a small in-memory cut of a
    page of rows already fetched for the state.
    """
    limit = _limit(options)
    rows = await runtime.staging.list_by_states(
        tuple(state.value for state in states),
        limit=limit,
        exam=options.exam,
        subject=options.subject,
        year=options.year,
    )
    if options.section is not None:
        rows = tuple(row for row in rows if row.provenance.scope.section == options.section)
    return rows


async def _record_failure(
    runtime: Runtime,
    item: StagingItem,
    exc: BaseException,
) -> None:
    """Keep the failure on the row, so a retry and a person both see it."""
    message = f"{type(exc).__name__}: {exc}".strip()
    if not message:
        message = type(exc).__name__
    failed = item.model_copy(
        update={
            "attempts": item.attempts + 1,
            "error": message,
            "updated_at": datetime.now(UTC),
        }
    )
    await runtime.staging.save(failed)


async def _advance(
    runtime: Runtime,
    item: StagingItem,
    gate: GateService,
) -> StagingItem:
    """Move one adapted row through the scrape-side states.

    The order is the contract: gate, then dedupe. The gate is first so a
    malformed row never reaches the index. Dedupe is last because it looks
    at the content the gate has accepted. Media is deliberately not here:
    a row that never passes either check must not upload a figure.
    """
    if item.state is State.ADAPTED:
        item = gate.apply(item)
        await runtime.staging.save(item)
        if item.state is State.REJECTED:
            return item
    if item.state is State.GATED:
        item = await runtime.dedupe.apply(item)
        await runtime.staging.save(item)
    if item.state is State.DEDUPED:
        await runtime.dedupe.remember(item, origin=BANK)
    return item


async def fetch(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Scrape one scope, gate it, and stop at deduped.

    This is the fast lane. It reads the source, validates the payload, runs
    the gate and the duplicate check, and writes the accepted row to the
    bank. It does not tag, describe, or upload a figure. The later stages
    pick the row out of the bank and take as long as they need.
    """
    source = require(runtime.source, "source")
    scope = _scope(options)
    result = TaskResult(task="fetch")

    if options.dry_run:
        coverage = await source.probe(scope)
        result.seen = coverage.item_count
        result.note(
            f"{source.profile.name}: {coverage.item_count} item(s) for "
            f"{scope.exam}/{scope.subject}/{scope.year}"
        )
        return result

    catalog = await runtime.catalog_for(scope.exam, scope.subject) if source.needs_catalog else None
    known_passages = set(await runtime.staging.passage_ids())
    limit = _limit(options)
    item: StagingItem | None = None

    try:
        async for raw in source.fetch(scope):
            if result.seen >= limit:
                break
            result.seen += 1
            item = None
            try:
                issues = source.validate(raw)
                if issues:
                    result.fail(f"{raw.external_key}: source invalid: {'; '.join(issues)}")
                    continue

                existing = await runtime.staging.load(raw.external_key)
                if existing is not None:
                    if existing.provenance.scope != raw.scope:
                        result.fail(
                            f"{raw.external_key}: the bank holds this id under a different scope"
                        )
                        continue
                    if existing.state in (
                        State.ADAPTED,
                        State.GATED,
                        State.DEDUPED,
                    ):
                        item = existing
                        result.note(f"{existing.id}: resuming at {existing.state.value}")
                    elif existing.state in (State.ACQUIRED, State.PLANNED):
                        item = source.adapt(raw, catalog)
                        await runtime.staging.save(item)
                    else:
                        result.skipped += 1
                        continue
                else:
                    item = source.adapt(raw, catalog)
                    await runtime.staging.save(item)

                if item.passage is not None:
                    known_passages.add(item.passage.id)
                gate = GateService(
                    catalog=catalog,
                    known_passage_ids=known_passages,
                )
                item = await _advance(runtime, item, gate)

                if item.state is State.DEDUPED:
                    result.done += 1
                elif item.state is State.REJECTED:
                    # A gate or dedupe refusal is the scrape doing its job,
                    # not a failed run. The row is kept in the bank with its
                    # reason, and it never reaches media. A crash or a source
                    # refusal still counts as a failure.
                    result.skipped += 1
                    result.note(
                        f"{item.id}: filtered at {item.state.value}: "
                        f"{item.error or item.state.value}"
                    )
                else:
                    result.skipped += 1
            except Exception as exc:
                logger.warning("fetch failed for %s: %s", raw.external_key, exc)
                result.fail(f"{raw.external_key}: {type(exc).__name__}: {exc}")
                if item is not None:
                    await _record_failure(runtime, item, exc)
    except Exception as exc:
        logger.exception("the source fetch failed")
        result.fail(f"{source.profile.name}: {type(exc).__name__}: {exc}")

    return result


async def capture(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Fetch and store the figures for deduped rows.

    This is the first point at which a figure can reach the media store. The
    scrape stops before it, so a row the gate refused or the duplicate check
    filtered never uploads a byte. That keeps the store free of images for
    rows that will never be used.

    The task is resumable and idempotent. A row already captured has no refs;
    it is re-indexed from the content it now holds, so a crash between the
    upload and the index write does not leave a stale key. Capturing changes
    the content hash and the near key because the inline moves from the
    source url to the stored name, so the row is checked for duplicates a
    second time after the swap. A duplicate found then is refused here and
    never reaches the catalogue.
    """
    ingestor = require(runtime.ingestor, "media store")
    result = TaskResult(task="capture")
    rows = await _rows(runtime, (State.DEDUPED,), options)

    for item in rows:
        result.seen += 1
        if not item.media_refs and not item.media_assets:
            result.skipped += 1
            result.note(f"{item.id}: no figures")
            continue
        if options.dry_run:
            result.note(f"{item.id}: would capture {len(item.media_refs)} figure(s)")
            continue
        try:
            captured = await ingestor.capture_refs(item)
            await runtime.index.forget_question(item.id, origin=BANK)
            found = await runtime.dedupe.find(captured)
            if found is not None:
                rejected = captured.transition_to(
                    State.REJECTED,
                    error=f"duplicate_{found.kind}: {found.question_id}",
                )
                await runtime.staging.save(rejected)
                result.skipped += 1
                result.note(f"{rejected.id}: duplicate after capture: {found.question_id}")
                continue
            await runtime.dedupe.remember(captured, origin=BANK)
            await runtime.staging.save(captured)
            result.done += 1
        except Exception as exc:
            logger.warning("capture failed for %s: %s", item.id, exc)
            result.fail(f"{item.id}: {type(exc).__name__}: {exc}")
            await _record_failure(runtime, item, exc)

    return result


async def tag(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Place deduped rows in the catalog. The catalogue step."""
    service = TagService(require(runtime.tagger, "tagger"))
    result = TaskResult(task="tag")
    rows = await _rows(runtime, (State.DEDUPED,), options)

    for item in rows:
        result.seen += 1
        if options.dry_run:
            result.note(f"{item.id}: would tag as {item.provenance.scope.subject}")
            continue
        try:
            catalog = await runtime.catalog_for(
                item.provenance.scope.exam,
                item.provenance.scope.subject,
            )
            catalogued = await service.tag(item, catalog)
            await runtime.staging.save(catalogued)
            result.done += 1
        except Exception as exc:
            logger.warning("tag failed for %s: %s", item.id, exc)
            result.fail(f"{item.id}: {type(exc).__name__}: {exc}")
            await _record_failure(runtime, item, exc)

    return result


async def media(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Finalize captured figures: move to media_ready and run the witnesses."""
    service = require(runtime.media, "media service")
    result = TaskResult(task="media")
    rows = await _rows(runtime, (State.CATALOGUED, State.MEDIA_READY), options)

    for item in rows:
        result.seen += 1
        if item.state is State.CATALOGUED and item.media_refs:
            result.skipped += 1
            result.note(f"{item.id}: figures have not been captured; run capture first")
            continue
        if options.dry_run:
            result.note(f"{item.id}: would describe {len(item.media_assets)} figure(s)")
            continue
        try:
            described = await service.apply(item)
            if described.state is State.DESCRIBED:
                await runtime.staging.save(described)
                result.done += 1
            elif described.state is State.CATALOGUED:
                result.skipped += 1
                result.note(f"{item.id}: no captured figures")
            else:
                await runtime.staging.save(described)
                result.skipped += 1
                result.note(f"{item.id}: left at {described.state.value}")
        except Exception as exc:
            logger.warning("media failed for %s: %s", item.id, exc)
            result.fail(f"{item.id}: {type(exc).__name__}: {exc}")
            await _record_failure(runtime, item, exc)

    return result


async def explain(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Explain the question. A row with captured figures waits for media."""
    service = ExplainService(require(runtime.explainer, "explainer"))
    result = TaskResult(task="explain")
    rows = await _rows(runtime, (State.DESCRIBED, State.CATALOGUED), options)

    for item in rows:
        result.seen += 1
        if item.state is State.CATALOGUED and (item.media_assets or item.media_refs):
            result.skipped += 1
            result.note(f"{item.id}: media has not run; run capture and media first")
            continue
        if options.dry_run:
            result.note(f"{item.id}: would explain")
            continue
        try:
            catalog = await runtime.catalog_for(
                item.provenance.scope.exam,
                item.provenance.scope.subject,
            )
            enriched = await service.explain(item, catalog)
            await runtime.staging.save(enriched)
            result.done += 1
        except Exception as exc:
            logger.warning("explain failed for %s: %s", item.id, exc)
            result.fail(f"{item.id}: {type(exc).__name__}: {exc}")
            await _record_failure(runtime, item, exc)

    return result


async def review(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Check the answer and explanation, and record the check."""
    service = ReviewService(require(runtime.verifier, "verifier"))
    result = TaskResult(task="review")
    rows = await _rows(runtime, (State.ENRICHED,), options)

    for item in rows:
        result.seen += 1
        if options.dry_run:
            result.note(f"{item.id}: would review")
            continue
        try:
            catalog = await runtime.catalog_for(
                item.provenance.scope.exam,
                item.provenance.scope.subject,
            )
            reviewed = await service.apply(item, catalog)
            await runtime.staging.save(reviewed)
            if reviewed.state is State.VERIFIED:
                result.done += 1
            else:
                result.block(f"{item.id}: {reviewed.error or reviewed.state.value}")
        except Exception as exc:
            logger.warning("review failed for %s: %s", item.id, exc)
            result.fail(f"{item.id}: {type(exc).__name__}: {exc}")
            await _record_failure(runtime, item, exc)

    return result


async def ready(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Check the bundle's conditions and promote the rows that meet them."""
    result = TaskResult(task="ready")
    rows = await _rows(runtime, (State.VERIFIED,), options)
    known_passages = await runtime.staging.passage_ids()

    for item in rows:
        result.seen += 1
        if options.dry_run:
            result.note(f"{item.id}: would run the ready conditions")
            continue
        try:
            catalog = await runtime.catalog_for(
                item.provenance.scope.exam,
                item.provenance.scope.subject,
            )
            service = ReadyService(
                catalog=catalog,
                known_passage_ids=known_passages,
            )
            bundle = service.promote([item])
            promoted = bundle.items[0]
            if promoted.state is State.READY:
                await runtime.staging.save(promoted)
                result.done += 1
            else:
                reasons: list[str] = []
                for condition in bundle.report.unmet():
                    detail = ", ".join(bundle.report.reason_for(condition))
                    reasons.append(f"{condition.value}: {detail or 'not met'}")
                result.block(f"{item.id}: not ready ({'; '.join(reasons)})")
        except Exception as exc:
            logger.warning("ready failed for %s: %s", item.id, exc)
            result.fail(f"{item.id}: {type(exc).__name__}: {exc}")
            await _record_failure(runtime, item, exc)

    return result


async def index(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Reload the production half of the content index."""
    result = TaskResult(task="index")

    if options.dry_run:
        async for _ in runtime.production.iter_known():
            result.seen += 1
        result.note(f"{result.seen} production question(s) would be indexed")
        return result

    # Read production completely before dropping anything. The read is the
    # slow, remote half, and a failure halfway through it must not leave the
    # bank with an empty index.
    questions = [known async for known in runtime.production.iter_known()]
    result.seen = len(questions)
    await runtime.index.forget(PRODUCTION)
    entries: list[tuple[str, str, str, str]] = []
    for known in questions:
        entries.append(
            (
                known.content_hash,
                known.near_duplicate,
                PRODUCTION,
                known.question_id,
            )
        )
        if len(entries) >= BATCH:
            await runtime.index.remember_many(entries, commit=False)
            result.done += len(entries)
            entries.clear()
    if entries:
        await runtime.index.remember_many(entries, commit=False)
        result.done += len(entries)
    await runtime.index.commit()

    total = await runtime.index.count()
    result.note(f"{result.done} production row(s) indexed; the index now holds {total}")
    return result


async def status(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Report what the bank holds. Reads only, never writes."""
    result = TaskResult(task="status")
    counts = await runtime.staging.counts_by_state()
    total = await runtime.index.count()
    production = await runtime.index.count(PRODUCTION)
    bank = await runtime.index.count(BANK)

    for state in State:
        result.note(f"{state.value:12} {counts.get(state.value, 0)}")
    result.note(f"{'index':12} {total} (production {production}, bank {bank})")
    return result


TASKS: dict[str, TaskFn] = {
    "fetch": fetch,
    "capture": capture,
    "tag": tag,
    "media": media,
    "explain": explain,
    "review": review,
    "ready": ready,
    "index": index,
    "status": status,
}

PRESETS: dict[str, tuple[str, ...]] = {
    "scrape": ("fetch",),
    "process": ("capture", "tag", "media", "explain", "review", "ready"),
}

TASK_HELP: dict[str, str] = {
    "fetch": "Scrape one scope, gate it, and stop at deduped. No media or models.",
    "capture": "Fetch and store figures for deduped rows, after the gate.",
    "tag": "Place deduped rows in the catalog.",
    "media": "Describe captured figures with two witnesses.",
    "explain": "Write the explanation and enrich the row.",
    "review": "Check the answer and record the verification.",
    "ready": "Check the ready conditions and promote the bundle.",
    "index": "Reload the production half of the content index.",
    "status": "Report counts per state and index size.",
}


async def run_named(
    name: str,
    runtime: Runtime,
    options: TaskOptions,
) -> TaskResult:
    """Run one task by name, or say the name is not a task."""
    task = TASKS.get(name)
    if task is None:
        known = ", ".join(TASKS)
        raise UsageError(f"unknown task {name!r}; known tasks: {known}")
    return await task(runtime, options)


async def run_preset(
    name: str,
    runtime: Runtime,
    options: TaskOptions,
) -> list[TaskResult]:
    """Run the tasks in a preset, in order, and keep every result.

    A preset does not stop at the first failed row. The rows that succeeded
    are real progress, and the next step can still work on them; the preset's
    exit status is the caller's to decide from the results.
    """
    steps = PRESETS.get(name)
    if steps is None:
        known = ", ".join(PRESETS)
        raise UsageError(f"unknown preset {name!r}; known presets: {known}")
    results: list[TaskResult] = []
    for step in steps:
        result = await run_named(step, runtime, options)
        results.append(result)
        logger.info("%s: %s", result.task, summary(result))
    return results


__all__ = [
    "DEFAULT_LIMIT",
    "PRESETS",
    "TASKS",
    "TASK_HELP",
    "TaskOptions",
    "TaskResult",
    "UsageError",
    "capture",
    "explain",
    "fetch",
    "index",
    "media",
    "ready",
    "review",
    "run_named",
    "run_preset",
    "status",
    "summary",
    "tag",
]
