"""The task protocol and the machinery every task inherits.

A task is one unit of work. It declares what it needs, what it fills, and
whether it may write the ready lane. It does not decide when it runs, and it
never calls another task.

Everything below the protocol exists so no task has to write it again:

- the run record, written once per execution
- the row loop, with the retry policy, so ``--on-error`` works everywhere
- the exit code, so a workflow notices that something failed
- the "requirement not met" refusal, so a task never quietly chains

That last one is why the pipeline's tasks each carried their own try and except:
there was no shared place to put the policy, so each one grew a slightly
different version of it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from utmelab_bank.config import Config, Lane
from utmelab_bank.errors import BankError, TaskError
from utmelab_bank.model.base import now_iso
from utmelab_bank.model.run import RowOutcome, Run
from utmelab_bank.store.repository import Repository
from utmelab_bank.store.selectors import Selector

if TYPE_CHECKING:
    from utmelab_bank.store.reference import ReferenceReader

__all__ = ["Task", "TaskContext", "TaskResult", "all_tasks", "get", "registered", "run_task"]

log = logging.getLogger(__name__)

#: How long to wait before the next attempt, per attempt number. Capped so a
#: row that keeps failing does not sit in the queue for a day.
_BACKOFF: tuple[int, ...] = (30, 300, 1800, 7200)


@dataclass(frozen=True)
class TaskResult:
    """What a run did. The exit code is derived from this, not set by hand."""

    run: Run
    outcomes: tuple[RowOutcome, ...] = ()

    @property
    def failed(self) -> int:
        return self.run.failed

    @property
    def exit_code(self) -> int:
        """1 when anything failed, so a workflow notices. 2 when the run broke."""
        if self.run.status == "broken":
            return 2
        return 1 if self.run.failed else 0

    def summary(self) -> str:
        return (
            f"{self.run.task} on {self.run.target}: "
            f"{self.run.succeeded} ok, {self.run.skipped} skipped, {self.run.failed} failed"
        )


@dataclass
class TaskContext:
    """Everything a task is allowed to reach.

    Handed in rather than imported, so a task cannot reach the database except
    through the repository, and cannot reach another task at all.
    """

    config: Config
    repo: Repository
    run: Run
    source_name: str = ""
    dry_run: bool = False
    #: The selector, logical table and limit the run was asked for. A batch task
    #: that does its own query in ``collect`` needs them, or ``--where`` and
    #: ``--limit`` would be silently ignored just for that task.
    where: str = "all"
    logical: str = "questions"
    limit: int | None = None
    #: What each row is missing, when a task refused it for an unmet
    #: requirement. Keyed by row id, so one row's missing step does not get
    #: attributed to the next one.
    missing: dict[str, str] = field(default_factory=dict)
    #: Production reference, opened only for tasks that declare
    #: ``needs_reference``. Read-only and cached for the run.
    reference: ReferenceReader | None = None

    def lane(self, lane: Lane) -> Repository:
        return self.repo.in_lane(lane)

    def ok(self, row_id: str) -> RowOutcome:
        return RowOutcome(row_id=row_id, state="ok")

    def skip(self, row_id: str, code: str, detail: str) -> RowOutcome:
        return RowOutcome(row_id=row_id, state="skipped", code=code, detail=detail)

    def fail(self, row_id: str, code: str, detail: str, *, retryable: bool = False) -> RowOutcome:
        return RowOutcome(
            row_id=row_id, state="failed", code=code, detail=detail, retryable=retryable
        )

    def refuse(self, row_id: str, requirement: str) -> RowOutcome:
        """Skip a row because ``requirement`` has not run for it.

        The wording names the step, so the operator is told what to run next
        rather than being told a row was skipped.
        """
        message = f"{requirement} has not run for this row"
        self.missing[row_id] = message
        return RowOutcome(row_id=row_id, state="skipped", code="requirement_unmet", detail=message)


@runtime_checkable
class Task(Protocol):
    """One unit of work. The whole interface is these five members."""

    name: str
    #: The column this task fills.
    produces: str
    #: Tasks whose output it consumes. A task never calls them; it refuses rows
    #: whose requirement is unmet.
    requires: tuple[str, ...]
    #: True only for promotion.
    may_write_ready: bool
    #: Human sentence for ``utmelab-bank tasks``.
    description: str
    #: Whether the task processes rows a selector picked. A task that creates its
    #: own rows, such as intake or a figure fetch, sets this false and does its
    #: work in ``collect``. Declared rather than inferred, because inferring it
    #: from registry membership meant an unregistered task silently processed
    #: nothing.
    iterates_rows: bool

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
        """Do the work for one row."""
        ...

    async def collect(self, ctx: TaskContext) -> list[RowOutcome]:
        """Work that is not per row. Returns outcomes for anything it touched."""
        ...


_TASKS: dict[str, Task] = {}


def registered(task: Task | type[Task]) -> Task | type[Task]:
    """Register a task.

    Takes a class and stores an instance, so the registry holds objects whose
    methods are bound. Registering the class itself is a trap: ``task.collect``
    then resolves to the unbound function and the call site looks correct right
    up until it fails.
    """
    instance = task() if isinstance(task, type) else task
    if instance.name in _TASKS:
        raise TaskError("duplicate task name", name=instance.name)
    _TASKS[instance.name] = instance
    return task


def all_tasks() -> tuple[str, ...]:
    return tuple(sorted(_TASKS))


def get(name: str) -> Task:
    try:
        return _TASKS[name]
    except KeyError as exc:
        raise TaskError("unknown task", name=name, known=all_tasks()) from exc


def _retry_at(attempt: int) -> str:
    """When the next attempt is due, for a row that failed attempt ``n``."""
    delay = _BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)]
    return (datetime.now(UTC) + timedelta(seconds=delay)).replace(microsecond=0).isoformat()


async def _process(
    task: Task,
    row: dict[str, Any],
    ctx: TaskContext,
    logical: str,
) -> RowOutcome:
    """One row, with the retry policy applied and the outcome persisted."""
    row_id = str(row.get("id", ""))
    try:
        outcome = await task.apply(row, ctx)
    except BankError as exc:
        outcome = ctx.fail(row_id, exc.code, str(exc), retryable=exc.is_retryable)
    except Exception as exc:
        # A bug in a task must fail its row, not the run. Otherwise one bad
        # question stops 199 good ones and nobody finds out why.
        log.exception("task %s raised on row %s", task.name, row_id)
        outcome = ctx.fail(row_id, "task_crashed", f"{type(exc).__name__}: {exc}")

    await _persist(logical, row_id, int(row.get("attempts") or 0), outcome, ctx)
    return outcome


async def _persist(
    logical: str,
    row_id: str,
    attempts: int,
    outcome: RowOutcome,
    ctx: TaskContext,
) -> None:
    """Record the outcome on the row, and schedule the next attempt if retrying.

    The table comes from what the caller asked for rather than from the registry,
    so a task that is exercised in a test without being registered still records
    its failures instead of dropping them on the floor.
    """
    if not row_id:
        return
    if outcome.state == "failed":
        retrying = outcome.retryable and ctx.config.on_error == "retry"
        await ctx.repo.mark_failed(
            logical,
            row_id,
            outcome.code or "failed",
            outcome.detail or "",
            retry_at=_retry_at(attempts + 1) if retrying else None,
        )
    elif outcome.state == "ok":
        await ctx.repo.clear_error(logical, row_id)


#: Which logical table each task's rows live in, for ``utmelab-bank tasks``.
#: Purely descriptive: the base class uses the table the caller passes.
_TASK_TABLE: dict[str, str] = {}


def declares_rows_in(logical: str) -> Callable[[type[Task]], type[Task]]:
    """Class decorator telling the base class which table a task's rows live in."""

    def wrap(cls: type[Task]) -> type[Task]:
        _TASK_TABLE[cls.name] = logical
        return cls

    return wrap


def _logical_for(task: Task) -> str | None:
    return _TASK_TABLE.get(task.name)


async def run_task(
    task: Task,
    config: Config,
    repo: Repository,
    *,
    where: str = "all",
    logical: str = "questions",
    limit: int | None = None,
    source: str = "",
    dry_run: bool = False,
    progress: Callable[[int, int], None] | None = None,
    reference: ReferenceReader | None = None,
) -> TaskResult:
    """Run one task over the rows a selector picks.

    The whole point of this function is that a task body contains no error
    handling, no paging, no run bookkeeping and no exit code. It contains the
    work.
    """
    run = Run(
        id=f"r_{uuid.uuid4().hex[:12]}",
        task=task.name,
        target=config.lane,
        selector=where,
        sink=config.sink,
    )
    ctx = TaskContext(
        config=config,
        repo=repo,
        run=run,
        source_name=source,
        dry_run=dry_run,
        where=where,
        logical=logical,
        limit=limit,
    )

    await repo.open_run(run)
    outcomes: list[RowOutcome] = []
    reader: ReferenceReader | None = None

    try:
        if reference is not None:
            ctx.reference = reference
        elif getattr(task, "needs_reference", False):
            from utmelab_bank.store.reference import Reference

            reader = await Reference.open(config)
            ctx.reference = reader

        collected = await task.collect(ctx)
        outcomes.extend(collected)
        for outcome in collected:
            run.counts(outcome)

        if not task.iterates_rows:
            finished = _finish(run, outcomes)
            await repo.record_outcomes(run.id, [(o.row_id, o.state, o.code) for o in outcomes])
            await repo.close_run(finished)
            return TaskResult(run=finished, outcomes=tuple(outcomes))

        seen = 0
        async for row in repo.iter_rows(logical, where):
            if limit is not None and seen >= limit:
                break
            seen += 1
            if ctx.config.on_error == "stop" and run.failed:
                run.status = "stopped"
                break
            outcome = await _process(task, row, ctx, logical)
            run.counts(outcome)
            outcomes.append(outcome)
            if progress is not None and seen % 25 == 0:
                progress(seen, run.total)
            if run.failed and ctx.config.on_error == "stop":
                run.status = "stopped"
                break

    except BankError as exc:
        log.error("task %s could not run: %s", task.name, exc)
        run.status = "broken"
        run.detail = str(exc)
    finally:
        if reader is not None:
            await reader.aclose()

    finished = _finish(run, outcomes)
    with contextlib.suppress(Exception):
        await repo.record_outcomes(run.id, [(o.row_id, o.state, o.code) for o in outcomes])
    await repo.close_run(finished)
    return TaskResult(run=finished, outcomes=tuple(outcomes))


def _finish(run: Run, outcomes: Sequence[RowOutcome]) -> Run:
    run.finished_at = now_iso()
    if run.status == "running":
        run.status = "done"
    unmet = sum(1 for o in outcomes if o.code == "requirement_unmet")
    if unmet:
        # Only when a requirement really is unmet. Logging every skip as a
        # missing requirement is how a task that skips rows because they are
        # already done starts looking like it is broken.
        log.info(
            "%s: %d rows skipped, %d for a missing requirement", run.task, len(outcomes), unmet
        )
    return run


async def gather_bounded(
    callables: Sequence[Callable[[], Awaitable[RowOutcome]]],
    *,
    concurrency: int,
) -> list[RowOutcome]:
    """Run independent coroutines with a ceiling, preserving order.

    Used by the model tasks, where each row is an independent request. The
    ceiling exists because the old verify scripts opened one request per
    question with no limit, and a 200 row run then looked like a denial of
    service to the model provider.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(call: Callable[[], Awaitable[RowOutcome]]) -> RowOutcome:
        async with semaphore:
            return await call()

    return list(await asyncio.gather(*(guarded(c) for c in callables), return_exceptions=False))


async def as_rows(source: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    """Materialise a row stream. Only for callers that genuinely need a list."""
    return [row async for row in source]


def selectors_for(_task: Task) -> tuple[Selector, ...]:
    """The selectors a task's rows can be picked with, for ``--explain``."""
    from utmelab_bank.store import selectors

    return tuple(selectors.describe(name) for name in selectors.all_names())
