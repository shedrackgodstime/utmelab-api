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

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from utmelab_bank.adapters.database import DatabaseError
from utmelab_bank.adapters.gate_service import GateService
from utmelab_bank.adapters.media import MediaError, MediaIngestor
from utmelab_bank.adapters.providers.factory import ProviderExhausted
from utmelab_bank.adapters.providers.openai_compatible import OpenAICompatibleError
from utmelab_bank.adapters.providers.opencode import OpenCodeError
from utmelab_bank.adapters.providers.tagging import ExplainService, TagService
from utmelab_bank.adapters.ready_service import ReadyService
from utmelab_bank.adapters.review_service import ReviewService
from utmelab_bank.adapters.store.index import BANK, BATCH, PRODUCTION
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import Scope, StagingItem
from utmelab_bank.domain.ports import Source
from utmelab_bank.domain.state import TERMINAL_STATES
from utmelab_bank.runtime import Runtime, require

logger = logging.getLogger(__name__)

#: How many rows a batch task takes when the caller does not say.
DEFAULT_LIMIT = 100

#: The most rows one batch task works on at once.
#:
#: A worker spends nearly all of its time waiting for a model, so a little
#: overlap buys most of the speedup. The database writes stay serialized
#: behind the client's single worker thread, and a free tier rate limit is
#: measured in requests per minute, not concurrency.
MAX_CONCURRENCY = 8

#: Consecutive failures a row may collect before it is quarantined as FAILED.
#:
#: A successful step clears the counter, so this is a retry ceiling for one
#: stuck row, not a lifetime budget across the pipeline. Without it a row can
#: spend provider calls forever, which is how ``myschool:67629`` reached 140
#: attempts.
MAX_ATTEMPTS = 5


class UsageError(RuntimeError):
    """The command was asked to do something it cannot do as written."""


@dataclass(frozen=True)
class TaskOptions:
    """What the caller told the task about the batch."""

    exam: str | None = None
    subject: str | None = None
    year: int | None = None
    section: str | None = None
    country: str | None = None
    limit: int | None = None
    max_failures: int = 3
    dry_run: bool = False
    concurrency: int = 1


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
    stopped: bool = False

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
            "stopped": self.stopped,
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
    country = options.country.upper() if options.country else None
    if options.exam.upper() == "WAEC" and country is None:
        raise UsageError("WAEC commands need --country, e.g. --country NG")
    return Scope(
        exam=options.exam,
        subject=options.subject,
        year=options.year,
        section=options.section,
        country=country,
    )


def _limit(options: TaskOptions) -> int:
    """The batch cap, with the default applied and a nonsense value refused."""
    limit = DEFAULT_LIMIT if options.limit is None else options.limit
    if limit <= 0:
        raise UsageError("--limit must be positive")
    return limit


def _max_failures(options: TaskOptions) -> int:
    """The consecutive-failure cap. Zero means no cap."""
    if options.max_failures < 0:
        raise UsageError("--max-failures cannot be negative")
    return options.max_failures


def _stop_after_failures(
    result: TaskResult,
    failures: int,
    options: TaskOptions,
) -> bool:
    """Record a stop when the consecutive-failure cap is reached."""
    limit = _max_failures(options)
    if limit and failures >= limit:
        result.stopped = True
        result.note(f"stopped after {failures} consecutive failure(s)")
        return True
    return False


#: Failures that mean the batch cannot make progress. A low-confidence tag or
#: an unknown subtopic is one row under review, not a dead provider, so those
#: never count towards the cap.
STOPPING_ERRORS = (
    ProviderExhausted,
    DatabaseError,
    MediaError,
    OpenCodeError,
    OpenAICompatibleError,
)


def _stops_the_batch(exc: BaseException) -> bool:
    """Whether this failure is a reason to stop asking for more rows."""
    return isinstance(exc, STOPPING_ERRORS)


def _concurrency(options: TaskOptions) -> int:
    """How many rows to work on at once, with a sane range enforced."""
    width = options.concurrency
    if width < 1:
        raise UsageError("--concurrency must be positive")
    if width > MAX_CONCURRENCY:
        raise UsageError(f"--concurrency cannot exceed {MAX_CONCURRENCY}")
    return width


@dataclass(frozen=True)
class Outcome:
    """What one worker did with its row, for the batch to count.

    ``done`` and ``skipped`` move a counter. ``blocked`` moves the blocked
    counter and carries the reason. ``note`` only records something the
    operator should see, such as a dry-run line.
    """

    kind: str
    note: str | None = None


DONE = Outcome("done")


def skipped(note: str | None = None) -> Outcome:
    return Outcome("skipped", note)


def blocked(note: str) -> Outcome:
    return Outcome("blocked", note)


def noted(note: str) -> Outcome:
    return Outcome("note", note)


async def _run_batch(
    runtime: Runtime,
    result: TaskResult,
    rows: Sequence[StagingItem],
    options: TaskOptions,
    worker: Callable[[StagingItem], Awaitable[Outcome]],
) -> None:
    """Run one worker per row, with a fixed number of rows in flight.

    This is a pool, not a barrier. When one call is slow (a reasoning model, a
    cold route, or a retry across accounts), the other workers keep pulling
    rows. A barrier would leave the other slots idle for the length of the
    slowest call in every chunk.

    The worker does the row's work and returns what happened; it does not
    touch the result. This function owns the counters, the failure record and
    the stop rules, so every task stops the same way. A stop stops new rows
    from starting; rows already in flight finish and are still recorded.

    The consecutive-failure rule is approximate above concurrency 1, because
    outcomes arrive in completion order. It still means what an operator
    needs: a run of stopping failures with no success between them.
    """
    width = _concurrency(options)
    queue: asyncio.Queue[StagingItem] = asyncio.Queue()
    for item in rows:
        queue.put_nowait(item)

    failures = 0
    stop = False

    async def consume() -> None:
        nonlocal failures, stop
        while not stop:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            result.seen += 1
            try:
                outcome = await worker(item)
            except Exception as exc:
                logger.warning("%s failed for %s: %s", result.task, item.id, exc)
                result.fail(f"{item.id}: {type(exc).__name__}: {exc}")
                await _record_failure(runtime, item, exc)
                if isinstance(exc, ProviderExhausted):
                    result.stopped = True
                    result.note(f"stopped: {exc}")
                    stop = True
                    return
                failures = failures + 1 if _stops_the_batch(exc) else 0
                if _stop_after_failures(result, failures, options):
                    stop = True
                    return
                continue
            failures = 0
            if outcome.kind == "done":
                result.done += 1
            elif outcome.kind == "skipped":
                result.skipped += 1
            elif outcome.kind == "blocked":
                result.block(outcome.note or f"{item.id}: blocked")
            elif outcome.note is not None:
                result.note(outcome.note)

    await asyncio.gather(*(consume() for _ in range(width)))


async def _rows(
    runtime: Runtime,
    states: tuple[State, ...],
    options: TaskOptions,
    *,
    has_media: bool | None = None,
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
        country=options.country.upper() if options.country else None,
        has_media=has_media,
    )
    if options.section is not None:
        rows = tuple(row for row in rows if row.provenance.scope.section == options.section)
    if options.country is not None:
        rows = tuple(row for row in rows if row.provenance.scope.country == options.country.upper())
    return rows


async def _record_failure(
    runtime: Runtime,
    item: StagingItem,
    exc: BaseException,
) -> None:
    """Keep the failure on the row, so a retry and a person both see it.

    A row that reaches the attempt ceiling is quarantined as ``FAILED`` with
    the last reason still attached. That keeps a broken row out of every later
    batch without hiding why it stopped.
    """
    message = f"{type(exc).__name__}: {exc}".strip()
    if not message:
        message = type(exc).__name__
    attempts = item.attempts + 1
    if attempts >= MAX_ATTEMPTS and item.state not in TERMINAL_STATES:
        failed = item.transition_to(
            State.FAILED,
            error=f"attempt_limit: {attempts} attempts; last error: {message}",
        ).model_copy(update={"attempts": attempts})
    else:
        failed = item.model_copy(
            update={
                "attempts": attempts,
                "error": message,
                "updated_at": datetime.now(UTC),
            }
        )
    await runtime.staging.save(failed)


async def _save_progress(runtime: Runtime, item: StagingItem) -> StagingItem:
    """Save a row that succeeded and clear an earlier failure from it.

    ``attempts`` counts consecutive failures, so a success resets it. Leaving
    the old count in place would let unrelated failures at different stages
    add up and quarantine a row that is still moving.
    """
    if item.attempts or item.error is not None:
        item = item.model_copy(
            update={"attempts": 0, "error": None, "updated_at": datetime.now(UTC)}
        )
    await runtime.staging.save(item)
    return item


async def _advance(
    runtime: Runtime,
    item: StagingItem,
    gate: GateService,
    ingestor: MediaIngestor,
) -> StagingItem:
    """Move one adapted row through the scrape-side states.

    The order is the contract: gate, then dedupe, then capture. The gate is
    first so a malformed row never reaches the index. Dedupe is second so a
    duplicate never causes a figure fetch. Capture is last because the source
    is alive now and may not be later, and only rows that passed both checks
    upload their bytes. The row stays at DEDUPED with its media_assets;
    the media step only finalizes and describes them later.
    """
    if item.state is State.ADAPTED:
        item = gate.apply(item)
        if item.state is State.REJECTED:
            # If the item was previously indexed (has content_hash), remove it.
            # A gate failure on a re-run means the item is no longer valid.
            if item.hashes and item.hashes.content_hash:
                await runtime.index.forget_question(item.id, origin=BANK)
            return item
    if item.state is State.GATED:
        item = await runtime.dedupe.apply(item)
        if item.state is State.REJECTED:
            # If the item was previously indexed (has content_hash), remove it.
            # A dedupe failure on a re-run means the item is a duplicate.
            if item.hashes and item.hashes.content_hash:
                await runtime.index.forget_question(item.id, origin=BANK)
            return item

    captured = False
    if item.media_refs or (item.media_blobs and not item.media_assets):
        # Capture figures now, while the source is alive. Only rows that
        # passed gate + dedupe reach here, so no wasted uploads.
        item = await ingestor.capture_refs(item)
        captured = True
    elif item.media_blobs:
        # A capture that predates the blob cleanup left the bytes behind.
        # The assets are already owned, so drop the stale source bytes.
        item = item.model_copy(update={"media_blobs": {}})

    if item.state is State.DEDUPED:
        if captured:
            # The inline swap may have changed the content hash. Drop the old
            # bank entry before checking and writing the new one.
            await runtime.index.forget_question(item.id, origin=BANK)
            found = await runtime.dedupe.find(item)
            if found is not None:
                return item.transition_to(
                    State.REJECTED,
                    error=f"duplicate_{found.kind}: {found.question_id}",
                )
        await runtime.dedupe.remember(item, origin=BANK)

    if item.state is State.DEDUPED and item.error is not None:
        # A capture that failed once and succeeded on a retry should not keep
        # the old reason on the row.
        item = item.model_copy(update={"error": None})
    return item


async def fetch(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Scrape one scope, gate it, and stop at deduped.

    This is the fast lane. It reads the source, validates the payload, runs
    the gate and the duplicate check, and writes the accepted row to the
    bank. It does not tag or describe the row. Figure capture may already have
    happened while the source was alive; the separate capture task resumes
    rows that still have pending media.
    """
    source = require(runtime.source, "source")
    scope = _scope(options)
    result = TaskResult(task="fetch")

    if options.dry_run:
        return await probe(source, options)

    catalog = (
        await runtime.catalog_for(scope.exam, scope.subject, scope.country)
        if source.needs_catalog
        else None
    )
    production_ids = await runtime.production.question_ids(
        exam=scope.exam,
        subject=scope.subject,
        year=scope.year,
    )
    seen_production_ids: set[str] = set()
    known_passages = set(await runtime.staging.passage_ids())
    states = await runtime.staging.states_for(
        exam=scope.exam,
        subject=scope.subject,
        year=scope.year,
        country=scope.country,
    )
    limit = _limit(options)
    item: StagingItem | None = None

    ingestor = require(runtime.ingestor, "media store")
    try:
        async for raw in source.fetch(scope):
            # A source error row is a rejection, not a real item. Counting it
            # against the limit lets a mismatched row on an early page stop
            # the run before the requested scope's rows are reached.
            if "error" not in raw.payload:
                if result.seen >= limit:
                    break
                result.seen += 1
            item = None
            try:
                issues = source.validate(raw)
                if issues:
                    # The source adapter deliberately turns an unusable row
                    # into an error item so the rest of the page can continue.
                    # These are source-quality exclusions, not runner
                    # failures. A validation issue on an otherwise adapted
                    # payload is still a real parser/data-contract failure.
                    if all(issue.startswith("source.error:") for issue in issues):
                        result.skipped += 1
                        result.note(f"{raw.external_key}: skipped source row: {'; '.join(issues)}")
                    else:
                        result.fail(f"{raw.external_key}: source invalid: {'; '.join(issues)}")
                    continue

                production_id = source.production_question_id(raw)
                if production_id is not None:
                    if production_id in production_ids or production_id in seen_production_ids:
                        result.skipped += 1
                        result.note(f"{raw.external_key}: production already holds {production_id}")
                        continue
                    seen_production_ids.add(production_id)

                known = states.get(raw.external_key)
                if known is not None:
                    state, has_error, pending_media = known
                    if state == State.DEDUPED.value and not has_error and not pending_media:
                        # A finished row needs no second load or capture.
                        result.done += 1
                        continue
                    if state not in (
                        State.ADAPTED.value,
                        State.GATED.value,
                        State.DEDUPED.value,
                        State.ACQUIRED.value,
                        State.PLANNED.value,
                    ):
                        result.skipped += 1
                        continue

                existing = (
                    await runtime.staging.load(raw.external_key) if known is not None else None
                )
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
                    else:
                        result.skipped += 1
                        continue
                else:
                    item = source.adapt(raw, catalog)

                if item.passage is not None:
                    known_passages.add(item.passage.id)
                gate = GateService(
                    catalog=catalog,
                    known_passage_ids=known_passages,
                )
                item = await _advance(runtime, item, gate, ingestor)
                if (
                    item.state is State.REJECTED
                    and item.error is not None
                    and item.error.startswith("duplicate_")
                ):
                    # A duplicate is counted, never stored. The index already
                    # holds the original, so writing the copy would only bloat
                    # the bank; a future scrape re-checks and refuses it again.
                    result.skipped += 1
                    result.note(
                        f"{item.id}: filtered at {item.state.value}: "
                        f"{item.error or item.state.value}"
                    )
                    continue
                if item.state in TERMINAL_STATES:
                    await runtime.staging.save(item)
                else:
                    item = await _save_progress(runtime, item)
                states[item.id] = (
                    item.state.value,
                    item.error is not None,
                    bool(item.media_refs) or bool(item.media_blobs),
                )

                if item.state is State.DEDUPED:
                    result.done += 1
                elif item.state is State.REJECTED:
                    # A gate or review refusal is the scrape doing its job, not
                    # a failed run. The row is kept in the bank with its reason,
                    # and it never reaches media.
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
                    states[item.id] = (
                        item.state.value,
                        True,
                        bool(item.media_refs) or bool(item.media_blobs),
                    )
    except Exception as exc:
        logger.exception("the source fetch failed")
        result.fail(f"{source.profile.name}: {type(exc).__name__}: {exc}")

    return result


async def probe(source: Source, options: TaskOptions) -> TaskResult:
    """Probe a source without opening or touching either database."""
    scope = _scope(options)
    coverage = await source.probe(scope)
    result = TaskResult(task="fetch", seen=coverage.item_count)
    result.note(
        f"{source.profile.name}: {coverage.item_count} item(s) for "
        f"{scope.exam}/{scope.subject}/{scope.year}"
    )
    if coverage.has_more:
        result.note("source reports more than one page")
    return result


async def capture(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Fetch and store the figures for deduped rows.

    This is the explicit retry point for figure capture. The scrape may capture
    figures while the source is alive, but rows with pending media can resume
    here. A row refused by the gate or duplicate check never reaches capture.

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
    # A row can be tagged before its source figure is captured. Keep that
    # row eligible here, otherwise ``catalogued + media_refs`` is a dead end:
    # media refuses to describe uncaptured refs and capture never sees it.
    rows = await _rows(runtime, (State.DEDUPED, State.CATALOGUED), options, has_media=True)

    async def one(item: StagingItem) -> Outcome:
        if not item.media_refs:
            # Already captured (has media_assets) or no figures at all.
            return skipped(f"{item.id}: no pending refs")
        if options.dry_run:
            return noted(f"{item.id}: would capture {len(item.media_refs)} figure(s)")
        captured = await ingestor.capture_refs(item)
        await runtime.index.forget_question(item.id, origin=BANK)
        found = await runtime.dedupe.find(captured)
        if found is not None:
            rejected = captured.transition_to(
                State.REJECTED,
                error=f"duplicate_{found.kind}: {found.question_id}",
            )
            await runtime.staging.save(rejected)
            return skipped(f"{rejected.id}: duplicate after capture: {found.question_id}")
        await runtime.dedupe.remember(captured, origin=BANK)
        await _save_progress(runtime, captured)
        return DONE

    await _run_batch(runtime, result, rows, options, one)
    return result


async def tag(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Place deduped rows in the catalog. The catalogue step."""
    service = TagService(require(runtime.tagger, "tagger"))
    result = TaskResult(task="tag")
    rows = await _rows(runtime, (State.DEDUPED,), options)

    async def one(item: StagingItem) -> Outcome:
        if options.dry_run:
            return noted(f"{item.id}: would tag as {item.provenance.scope.subject}")
        catalog = await runtime.catalog_for(
            item.provenance.scope.exam,
            item.provenance.scope.subject,
            item.provenance.scope.country,
        )
        if not catalog.subtopics:
            return blocked(
                f"{item.id}: no catalog subtopics for "
                f"{item.provenance.scope.exam}/{item.provenance.scope.subject}"
            )
        catalogued = await service.tag(item, catalog)
        await _save_progress(runtime, catalogued)
        return DONE

    await _run_batch(runtime, result, rows, options, one)
    return result


async def media(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Finalize captured figures: move to media_ready and run the witnesses."""
    service = require(runtime.media, "media service")
    result = TaskResult(task="media")
    rows = await _rows(runtime, (State.CATALOGUED, State.MEDIA_READY), options, has_media=True)

    async def one(item: StagingItem) -> Outcome:
        if item.state is State.CATALOGUED and item.media_refs:
            return skipped(f"{item.id}: figures have not been captured; run capture first")
        if options.dry_run:
            return noted(f"{item.id}: would describe {len(item.media_assets)} figure(s)")
        described = await service.apply(item)
        if described.state is State.DESCRIBED:
            await _save_progress(runtime, described)
            return DONE
        if described.state is State.CATALOGUED:
            return skipped(f"{item.id}: no captured figures")
        await runtime.staging.save(described)
        return skipped(f"{item.id}: left at {described.state.value}")

    await _run_batch(runtime, result, rows, options, one)
    return result


async def explain(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Explain the question. A row with captured figures waits for media."""
    service = ExplainService(require(runtime.explainer, "explainer"))
    result = TaskResult(task="explain")
    rows = await _rows(runtime, (State.DESCRIBED, State.CATALOGUED), options)

    async def one(item: StagingItem) -> Outcome:
        if item.state is State.CATALOGUED and (item.media_assets or item.media_refs):
            return skipped(f"{item.id}: media has not run; run capture and media first")
        if options.dry_run:
            return noted(f"{item.id}: would explain")
        catalog = await runtime.catalog_for(
            item.provenance.scope.exam,
            item.provenance.scope.subject,
            item.provenance.scope.country,
        )
        enriched = await service.explain(item, catalog)
        await _save_progress(runtime, enriched)
        return DONE

    await _run_batch(runtime, result, rows, options, one)
    return result


async def review(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Check the answer and explanation, and record the check."""
    service = ReviewService(require(runtime.verifier, "verifier"))
    result = TaskResult(task="review")
    rows = await _rows(runtime, (State.ENRICHED,), options)

    async def one(item: StagingItem) -> Outcome:
        if options.dry_run:
            return noted(f"{item.id}: would review")
        catalog = await runtime.catalog_for(
            item.provenance.scope.exam,
            item.provenance.scope.subject,
            item.provenance.scope.country,
        )
        reviewed = await service.apply(item, catalog)
        if reviewed.state is State.VERIFIED:
            await _save_progress(runtime, reviewed)
            return DONE
        await runtime.staging.save(reviewed)
        return blocked(f"{item.id}: {reviewed.error or reviewed.state.value}")

    await _run_batch(runtime, result, rows, options, one)
    return result


async def ready(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Check the bundle's conditions and promote the rows that meet them."""
    result = TaskResult(task="ready")
    rows = await _rows(runtime, (State.VERIFIED,), options)
    known_passages = await runtime.staging.passage_ids()

    async def one(item: StagingItem) -> Outcome:
        if options.dry_run:
            return noted(f"{item.id}: would run the ready conditions")
        catalog = await runtime.catalog_for(
            item.provenance.scope.exam,
            item.provenance.scope.subject,
            item.provenance.scope.country,
        )
        service = ReadyService(
            catalog=catalog,
            known_passage_ids=known_passages,
        )
        bundle = service.promote([item])
        promoted = bundle.items[0]
        if promoted.state is State.READY:
            await _save_progress(runtime, promoted)
            return DONE
        reasons: list[str] = []
        for condition in bundle.report.unmet():
            detail = ", ".join(bundle.report.reason_for(condition))
            reasons.append(f"{condition.value}: {detail or 'not met'}")
        return blocked(f"{item.id}: not ready ({'; '.join(reasons)})")

    await _run_batch(runtime, result, rows, options, one)
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
    with_error, at_cap, highest = await runtime.staging.failure_counts(MAX_ATTEMPTS)
    total = await runtime.index.count()
    production = await runtime.index.count(PRODUCTION)
    bank = await runtime.index.count(BANK)

    for state in State:
        result.note(f"{state.value:12} {counts.get(state.value, 0)}")
    result.note(
        f"{'errors':12} {with_error} row(s) with a stored error, "
        f"{at_cap} at or over the attempt cap (max attempts {highest})"
    )
    result.note(f"{'index':12} {total} (production {production}, bank {bank})")
    return result


async def index_sync(runtime: Runtime, options: TaskOptions) -> TaskResult:
    """Sync the bank index with staging: remove orphans, report drift.

    Reads only by default (--dry-run). With --apply, removes index entries
    for items no longer in staging or in non-indexable states, and re-indexes
    items that should be indexed (DEDUPED and later) but aren't.
    """
    result = TaskResult(task="index-sync")

    # Both staging and index use the same bank client
    client = runtime.staging._client  # type: ignore[attr-defined]

    # States that should be indexed (DEDUPED and later, non-terminal)
    indexed_states = (
        "'deduped', 'catalogued', 'media_ready', 'described', "
        "'enriched', 'verified', 'ready', 'live', 'reported'"
    )
    # States that should NOT be indexed
    non_indexed_states = "'planned', 'acquired', 'adapted', 'gated', 'rejected', 'failed'"

    # Count orphans (no staging row at all)
    orphan_result = await client.execute("""
        SELECT COUNT(*) FROM content_index ci
        LEFT JOIN staging_items si ON ci.question_id = si.id
        WHERE ci.origin = 'bank' AND si.id IS NULL
    """)
    orphan_count = int(orphan_result.rows[0][0])

    # Count mis-indexed (staging items in non-indexable states but in index)
    misindexed_result = await client.execute(f"""
        SELECT COUNT(*) FROM content_index ci
        JOIN staging_items si ON ci.question_id = si.id
        WHERE ci.origin = 'bank' AND si.state IN ({non_indexed_states})
    """)
    misindexed_count = int(misindexed_result.rows[0][0])

    # Count missing (staging items in indexable states not in index)
    missing_result = await client.execute(f"""
        SELECT COUNT(*) FROM staging_items si
        LEFT JOIN content_index ci ON si.id = ci.question_id AND ci.origin = 'bank'
        WHERE ci.question_id IS NULL AND si.state IN ({indexed_states}) AND si.content_hash != ''
    """)
    missing_count = int(missing_result.rows[0][0])

    result.note(f"Orphaned index entries (no staging row): {orphan_count}")
    result.note(f"Mis-indexed entries (staging row in non-indexable state): {misindexed_count}")
    result.note(
        f"Missing index entries (staging row in indexable state not indexed): {missing_count}"
    )

    if options.dry_run:
        result.note("DRY RUN: no changes made. Use --apply to fix.")
        return result

    if orphan_count > 0:
        await client.execute("""
            DELETE FROM content_index
            WHERE origin = 'bank'
            AND question_id NOT IN (SELECT id FROM staging_items)
        """)
        result.done += orphan_count
        result.note(f"Removed {orphan_count} orphaned index entries")

    if misindexed_count > 0:
        await client.execute(f"""
            DELETE FROM content_index
            WHERE origin = 'bank'
            AND question_id IN (SELECT id FROM staging_items WHERE state IN ({non_indexed_states}))
        """)
        result.done += misindexed_count
        result.note(f"Removed {misindexed_count} mis-indexed entries")

    if missing_count > 0:
        # Re-index missing items
        missing_items = await client.execute(f"""
            SELECT si.id, si.content_hash, si.bundle_hash
            FROM staging_items si
            LEFT JOIN content_index ci ON si.id = ci.question_id AND ci.origin = 'bank'
            WHERE ci.question_id IS NULL AND si.state IN ({indexed_states}) AND si.content_hash != ''
        """)
        entries = []
        for row in missing_items.rows:
            question_id, content_hash, bundle_hash = row
            entries.append((content_hash, content_hash, BANK, question_id))

        if entries:
            await runtime.index.remember_many(entries)
            await runtime.index.commit()
            result.done += len(entries)
            result.note(f"Re-indexed {len(entries)} missing items")

    total = await runtime.index.count()
    bank = await runtime.index.count(BANK)
    result.note(f"Index now holds {total} (bank {bank})")
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
    "index-sync": index_sync,
    "status": status,
}

PRESETS: dict[str, tuple[str, ...]] = {
    "scrape": ("fetch",),
    "process": ("capture", "tag", "media", "explain", "review", "ready"),
}

TASK_HELP: dict[str, str] = {
    "fetch": "Scrape one scope, gate it, capture figures, and stop at deduped.",
    "capture": "Capture figures for deduped rows that still need media.",
    "tag": "Place deduped rows in the catalog.",
    "media": "Describe captured figures with two witnesses.",
    "explain": "Write the explanation and enrich the row.",
    "review": "Check the answer and record the verification.",
    "ready": "Check the ready conditions and promote the bundle.",
    "index": "Reload the production half of the content index.",
    "index-sync": "Sync bank index with staging (remove orphans, re-index missing).",
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
    for index, step in enumerate(steps):
        result = await run_named(step, runtime, options)
        results.append(result)
        logger.info("%s: %s", result.task, summary(result))
        if result.stopped:
            remaining = steps[index + 1 :]
            if remaining:
                result.note(f"preset stopped; not run: {', '.join(remaining)}")
            break
    return results


__all__ = [
    "DEFAULT_LIMIT",
    "PRESETS",
    "TASKS",
    "TASK_HELP",
    "TaskOptions",
    "TaskResult",
    "UsageError",
    "explain",
    "fetch",
    "index",
    "media",
    "probe",
    "ready",
    "review",
    "run_named",
    "run_preset",
    "status",
    "summary",
    "tag",
]
