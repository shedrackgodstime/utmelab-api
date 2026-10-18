"""Promotion: work rows become ready rows.

The only task permitted to write the ready lane, and the only one that moves a
row between tables. Everything before it works on a draft; everything after it
is a candidate for production.

Three conditions, all checked here rather than assumed upstream:

- The row passed the mechanical gate.
- Its content hash is stamped, because the API joins on it and a row without one
  is silently unverified.
- It is not already in the ready lane, so promotion is idempotent.

The move is a copy rather than a rename. A rename would destroy the draft, and
the draft is what a human goes back to when a ready row turns out to be wrong.
"""

from __future__ import annotations

from typing import Any

from utmelab_bank.errors import TaskError
from utmelab_bank.model.base import now_iso
from utmelab_bank.model.run import RowOutcome
from utmelab_bank.task.base import TaskContext, registered, run_task

__all__ = ["Promote", "promote_rows"]

#: Columns a work row carries that the ready row does not. Staging bookkeeping
#: stops at promotion, which is the point of the lane.
#:
#: ``fingerprint`` goes because it is an internal dedupe key and the API has no
#: column for it. The provenance triple stays, because a ready row is still a
#: question we fetched from somewhere, and dropping it loses the only record of
#: where the content came from.
_DROP = frozenset(
    {
        "fingerprint",
        "gate_reason",
        "attempts",
        "error",
        "next_retry_at",
        "created_at",
    }
)

#: How many rows one promotion moves. Small enough that a mistake is a small
#: mistake, large enough that 200 rows is not 200 round trips.
BATCH: int = 200


@registered
class Promote:
    """Move gated rows from the work lane into the ready lane."""

    name = "promote"
    produces = "ready_questions"
    requires: tuple[str, ...] = ("gate",)
    may_write_ready = True
    iterates_rows = True
    description = "Move gated, hashed work rows into the ready lane. The only ready writer."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
        return await promote_one(row, ctx)

    async def collect(self, _ctx: TaskContext) -> list[RowOutcome]:
        return []


async def promote_one(row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
    """Copy one work row into the ready lane, with the conditions checked."""
    row_id = str(row.get("id", ""))
    target = ctx.repo.in_lane("ready")

    if not row.get("content_hash"):
        return ctx.skip(row_id, "no_content_hash", "the row carries no content hash")

    if await target.count("questions", f"id={row_id}"):
        # Already promoted. Reported as a skip rather than a success, because a
        # re-run that reports twelve promotions moved nothing and that is worth
        # being able to see.
        return ctx.skip(row_id, "already_ready", "this row is already in the ready lane")

    if ctx.dry_run:
        return ctx.ok(row_id)

    await target.insert_many("questions", [ready_row(row, ctx.run.id)])
    return ctx.ok(row_id)


def ready_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    """The ready-lane shape of a work row.

    ``section`` is carried across explicitly rather than by omission, because
    the pipeline forgot it at exactly this step and every synced question has a
    null section to this day.
    """
    stamp = now_iso()
    ready: dict[str, Any] = {
        key: value for key, value in row.items() if key not in _DROP and key != "id"
    }
    ready["id"] = row["id"]
    # Carried explicitly, because carrying a column by omission is how
    # ``section`` ended up null on every question the pipeline ever promoted.
    ready["section"] = row.get("section")
    ready["gate_status"] = "pass"
    ready["run_id"] = run_id
    ready["created_at"] = stamp
    ready["updated_at"] = stamp
    ready["attempts"] = 0
    ready["error"] = None
    ready["next_retry_at"] = None
    return ready


async def promote_rows(
    ctx: TaskContext,
    *,
    where: str = "gated",
    limit: int | None = None,
) -> list[Any]:
    """Run promotion over a selector. Thin wrapper so a goal can call it."""
    result = await run_task(
        Promote(),
        ctx.config,
        ctx.repo,
        where=where,
        logical="questions",
        limit=limit,
        dry_run=ctx.dry_run,
    )
    return list(result.outcomes)


def require_promotable(row: dict[str, Any]) -> None:
    """Raise when a row must not be promoted. Used by tests and by a goal."""
    if row.get("gate_status") != "pass":
        raise TaskError("row has not passed the gate", row=str(row.get("id")))
    if not row.get("content_hash"):
        raise TaskError("row has no content hash", row=str(row.get("id")))
