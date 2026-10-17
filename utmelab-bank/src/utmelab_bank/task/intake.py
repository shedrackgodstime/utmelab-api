"""Intake: raw rows become work rows.

The one task that moves rows between lanes, and it is deliberately separate from
``scrape`` so that a re-scrape cannot collide with work in flight. ``scrape``
writes the raw lane and nothing else; ``intake`` is the only thing that reads raw
and writes work.

What it does, in order, and why each step is here rather than in the harvester:

1. Skip anything already in the work lane. Re-running intake is then free.
2. Apply the mechanical gate. A row that cannot be answered as it stands never
   enters the work lane at all, so nothing downstream, including the model, is
   ever asked about it.
3. Carry ``section`` across. The pipeline's staging table had no ``section``
   column, so every question it promoted had a null one while the contract
   stayed green. The column exists here from the first migration.
4. Stamp the content hash. The repository does it for every question write, and
   a row without it is silently unverified for every candidate who sees it.

Figures are discovered here too, not fetched. ``media-discover`` records them and
``media_fetch`` gets them, so scraping never depends on the image host being up.
"""

from __future__ import annotations

import logging
from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.task.base import Task, TaskContext, registered
from utmelab_bank.rules import GateVerdict, judge_row

__all__ = ["Intake", "work_row", "refuse"]

log = logging.getLogger(__name__)

#: How many raw rows one intake reads. Bounded so a mistake on a whole paper is
#: a mistake on part of one, and so the run is restartable at a known point.
BATCH: int = 200


@registered
class Intake:
    """Move raw rows into the work lane, refusing what cannot be used."""

    name = "intake"
    produces = "work_questions"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    #: Reads its own rows: it is the one task that bridges two lanes.
    iterates_rows = False
    description = "Move raw rows into work, applying the gate and recording figures."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> Any:
        raise NotImplementedError

    async def collect(self, ctx: TaskContext) -> list[Any]:
        return await run_intake(ctx)


async def run_intake(ctx: TaskContext, *, limit: int | None = None) -> list[Any]:
    """Read raw rows, judge them, and write the survivors into work."""
    raw = ctx.repo.in_lane("raw")
    work = ctx.repo

    existing = {row["id"] for row in await work.rows("questions")}
    cap = limit or BATCH

    outcomes: list[Any] = []
    kept: list[dict[str, Any]] = []
    refused = 0
    figures = 0

    async for row in raw.iter_rows("questions", batch=cap):
        row_id = str(row.get("id", ""))
        if not row_id:
            continue
        if row_id in existing:
            outcomes.append(ctx.skip(row_id, "already_in_work", "this row is already in the work lane"))
            continue

        verdict = judge_raw(row)
        if not verdict.passed:
            refused += 1
            outcomes.append(ctx.skip(row_id, "gate_refused", verdict.reason))
            if not ctx.dry_run:
                await raw.update(
                    "questions",
                    row_id,
                    {"gate_status": "refused", "gate_reason": verdict.reason},
                )
            continue

        figures += len(verdict.figures)
        kept.append(work_row(row, verdict, ctx.run.id))
        outcomes.append(ctx.ok(row_id))
        if len(kept) >= cap:
            break

    if kept and not ctx.dry_run:
        await work.insert_many("questions", kept)

    log.info(
        "intake: %d into work, %d refused, %d already there, %d figures",
        len(kept),
        refused,
        len(outcomes) - len(kept) - refused,
        figures,
    )
    return outcomes


def judge_raw(row: dict[str, Any]) -> GateVerdict:
    """Apply the rules to a raw row, before it becomes a work row.

    A thin name over the shared judge, kept because "raw row" says what it is
    being asked here, and the raw lane and the work lane store the same columns
    so there is only one shape to read.
    """
    return judge_row(row)


def work_row(row: dict[str, Any], verdict: GateVerdict, run_id: str) -> dict[str, Any]:
    """The work-lane shape of a raw row that passed the gate.

    A copy rather than a rename, so the raw row survives as the record of what
    the site said. That record is what a re-parse compares against, and it is
    the only way to see that the site edited a question after the fact.
    """
    stamp = now_iso()
    work: dict[str, Any] = dict(row)
    work["gate_status"] = "pass"
    work["gate_reason"] = None
    work["error"] = None
    work["next_retry_at"] = None
    work["attempts"] = 0
    work["run_id"] = run_id
    work["created_at"] = stamp
    work["updated_at"] = stamp
    return work


def refuse(row: dict[str, Any]) -> tuple[str, str]:
    """The reason a raw row cannot enter the work lane, as ``(status, reason)``."""
    verdict = judge_raw(row)
    if verdict.passed:
        return ("pass", "")
    return ("refused", verdict.reason)
