"""The fill loop: walk the plan until the source is dry or the budget is spent.

This is acquisition, not enrichment. It knows the source, the exam, the
subject and the year, and nothing else. The taxonomy is an enrichment input;
it never steers a scrape.

The plan is a table, so a run that stops at its budget leaves the next run
exactly where this one stopped. A target is picked, fetched to its last page,
and marked. Dedupe happens at the raw index, so a re-run costs requests but
never rows.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from utmelab_bank.config import Config
from utmelab_bank.errors import ConfigError, SourceError
from utmelab_bank.model.base import now_iso
from utmelab_bank.source.base import FetchRequest
from utmelab_bank.source.myschool.run import fetch_subject
from utmelab_bank.source.myschool.subjects import ExamSubjects, SubjectEntry, subjects_for
from utmelab_bank.source.raw import raw_passage_row, raw_row
from utmelab_bank.store import targets
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository

__all__ = ["Batch", "FillOptions", "FillReport", "myschool_fetch", "plan", "run_fill"]

#: How many empty or zero-new targets a subject may have in one run before it
#: is set aside. It is not written off; the next run tries it again.
DRY_LIMIT = 3


@dataclass(frozen=True)
class Batch:
    """What one target fetch produced, and how many pages it walked."""

    parsed: list[Any]
    pages: int = 0


Fetch = Callable[[FetchRequest], Awaitable[Batch]]


@dataclass(frozen=True)
class FillOptions:
    """The slice to fill and the budget to fill it with."""

    source: str = "myschool"
    exam: str = "jamb"
    subjects: tuple[str, ...] = ()
    from_year: int | None = None
    to_year: int | None = None
    minutes: float = 50.0
    max_targets: int | None = None
    delay: float | None = None
    strategy: str = "api"
    refresh: bool = False


@dataclass
class FillReport:
    """What one run did, in terms a workflow summary can print."""

    source: str
    exam: str
    database: str
    seeded: int = 0
    reset: int = 0
    attempted: int = 0
    rows_seen: int = 0
    rows_new: int = 0
    drained: int = 0
    empty: int = 0
    failed: int = 0
    elapsed: float = 0.0
    reason: str = ""
    plan: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"fill {self.source} {self.exam}: {self.attempted} targets, "
            f"{self.rows_seen} seen, {self.rows_new} new"
        )


def myschool_fetch(config: Config, *, strategy: str) -> Fetch:
    """A fetcher bound to the myschool source.

    The loop takes a callable rather than importing the source directly, so a
    test can drive the plan with a fake and no network.
    """

    async def fetch(request: FetchRequest) -> Batch:
        pages = 0

        def on_item(page: int, _last: int) -> None:
            nonlocal pages
            pages = max(pages, int(page or 0))

        parsed = await fetch_subject(request, config, strategy=strategy, on_item=on_item)
        return Batch(parsed=parsed, pages=pages)

    return fetch


def _scope(options: FillOptions) -> tuple[ExamSubjects, list[tuple[SubjectEntry, int]], list[int]]:
    """Resolve the exam, the subjects and the year window.

    The subject map is the only list of subjects. It is the source's own map,
    so an unmapped subject is a refusal rather than a guess.
    """
    exam = options.exam.lower()
    mapped = subjects_for(exam)

    indexed = list(enumerate(mapped.subjects))
    by_slug = {entry.slug: (entry, index) for index, entry in indexed}
    by_source = {entry.source: (entry, index) for index, entry in indexed}

    if options.subjects:
        chosen: list[tuple[SubjectEntry, int]] = []
        seen: set[str] = set()
        for name in options.subjects:
            found = by_slug.get(name) or by_source.get(name)
            if found is None:
                raise SourceError(
                    "that subject is not in the source map",
                    exam=exam,
                    subject=name,
                    known=[entry.slug for entry in mapped.subjects][:8],
                )
            entry, index = found
            if entry.slug not in seen:
                chosen.append((entry, index))
                seen.add(entry.slug)
        subjects = chosen
    else:
        subjects = [(entry, index) for index, entry in indexed]

    to_year = options.to_year if options.to_year is not None else mapped.default_year
    from_year = options.from_year if options.from_year is not None else to_year - 10
    if from_year > to_year:
        raise ConfigError(
            "the year window is backwards",
            from_year=from_year,
            to_year=to_year,
        )
    years = list(range(to_year, from_year - 1, -1))
    return mapped, subjects, years


def plan(options: FillOptions) -> list[dict[str, Any]]:
    """The ordered targets, without touching the database.

    Newest year first, then the subjects in the map's own order, so every
    subject gets content early instead of one subject draining first.
    """
    _, subjects, years = _scope(options)
    rows: list[dict[str, Any]] = []
    for year in years:
        for entry, order in subjects:
            rows.append(
                {
                    "source": options.source,
                    "exam": options.exam.lower(),
                    "subject": entry.slug,
                    "subject_order": order,
                    "year": year,
                }
            )
    return rows


async def _run_target(
    store: Store,
    raw: Repository,
    target: dict[str, Any],
    *,
    exam: str,
    options: FillOptions,
    fetch: Fetch,
    run_id: str,
) -> tuple[str, int, int]:
    """Fetch one target and record the outcome.

    Returns ``(outcome, rows_seen, rows_new)``. ``outcome`` is ``drained``,
    ``empty`` or ``failed``. A source failure is caught here because one bad
    target is a retry, not a lost run. A database failure is not caught; that
    should stop the run rather than be recorded as a source problem.
    """
    subject = str(target["subject"])
    year = int(target["year"])
    await targets.mark_active(store, target)
    request = FetchRequest(exam=exam, subject=subject, year=year, delay=options.delay)
    try:
        batch = await fetch(request)
    except Exception as exc:  # noqa: BLE001 - one bad target is a retry, not a lost run
        await targets.mark_failed(store, target, f"{type(exc).__name__}: {exc}")
        return "failed", 0, 0

    rows = [raw_row(item, run_id) for item in batch.parsed]
    passages = [row for item in batch.parsed if (row := raw_passage_row(item)) is not None]
    if passages:
        await raw.insert_many("passages", passages)
    written = await raw.insert_many("questions", rows)
    if not batch.parsed:
        await targets.mark_empty(store, target, pages=batch.pages)
        return "empty", 0, 0
    await targets.mark_drained(
        store,
        target,
        rows_seen=len(batch.parsed),
        rows_new=written,
        pages=batch.pages,
    )
    return "drained", len(batch.parsed), written


async def run_fill(
    config: Config,
    store: Store,
    options: FillOptions,
    *,
    fetch: Fetch | None = None,
) -> FillReport:
    """Seed the slice, then fetch targets until the budget or the queue ends."""
    if options.source != "myschool":
        raise SourceError(
            "the fill planner has no adapter for that source",
            source=options.source,
            known=["myschool"],
        )
    if options.minutes <= 0:
        raise ConfigError("the minute budget must be positive", minutes=options.minutes)

    _, subjects, years = _scope(options)
    fetcher = fetch or myschool_fetch(config, strategy=options.strategy)
    report = FillReport(source=options.source, exam=options.exam.lower(), database=store.url)

    report.seeded = await targets.seed(
        store,
        source=options.source,
        exam=report.exam,
        subjects=[(entry.slug, order) for entry, order in subjects],
        years=years,
    )
    if options.refresh:
        report.reset = await targets.reset(
            store,
            source=options.source,
            exam=report.exam,
            subjects=[entry.slug for entry, _ in subjects],
            years=years,
        )

    run_id = f"r_fill_{now_iso().replace(':', '').replace('-', '')}"
    raw = Repository(store, lane="raw")
    dry: dict[str, int] = {}
    started = time.monotonic()
    reason = "done"

    while True:
        if options.max_targets is not None and report.attempted >= options.max_targets:
            reason = "limit"
            break
        if time.monotonic() - started >= options.minutes * 60:
            reason = "budget"
            break

        excluded = {subject for subject, count in dry.items() if count >= DRY_LIMIT}
        target = await targets.next_target(
            store,
            source=options.source,
            exam=report.exam,
            exclude_subjects=excluded,
        )
        if target is None:
            reason = "done"
            break

        outcome, seen, new = await _run_target(
            store,
            raw,
            target,
            exam=report.exam,
            options=options,
            fetch=fetcher,
            run_id=run_id,
        )
        report.attempted += 1
        report.rows_seen += seen
        report.rows_new += new
        subject = str(target["subject"])
        if outcome == "failed":
            report.failed += 1
        elif outcome == "empty":
            report.empty += 1
            dry[subject] = dry.get(subject, 0) + 1
        else:
            report.drained += 1
            dry[subject] = 0 if new else dry.get(subject, 0) + 1

    report.elapsed = time.monotonic() - started
    report.reason = reason
    report.plan = await targets.counts(store, source=options.source, exam=report.exam)
    return report
