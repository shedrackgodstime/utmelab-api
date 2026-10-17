"""The mechanical gate: record the rules' verdict on a work row.

The rules themselves live in :mod:`utmelab_bank.rules`, because two things need
them and only one of them is a task.
"""

from __future__ import annotations

from typing import Any

from utmelab_bank.rules import judge_row
from utmelab_bank.task.base import TaskContext, declares_rows_in, registered

__all__ = ["MechanicalGate", "judge_row"]


@registered
@declares_rows_in("questions")
class MechanicalGate:
    """Records the rules' verdict on a work row."""

    name = "gate"
    produces = "gate_status"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = True
    description = "Refuse rows with no usable options, a bad key, or a missing figure."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> Any:
        return await record_verdict(row, ctx)

    async def collect(self, ctx: TaskContext) -> list[Any]:
        return []


async def record_verdict(row: dict[str, Any], ctx: TaskContext) -> Any:
    """Judge one work row and write the verdict onto it."""
    from utmelab_bank.model.base import now_iso

    row_id = str(row.get("id", ""))
    if ctx.dry_run:
        return ctx.ok(row_id)

    verdict = judge_row(row)
    await ctx.repo.update(
        "questions",
        row_id,
        {
            "gate_status": "pass" if verdict.passed else "refused",
            "gate_reason": None if verdict.passed else verdict.reason,
            "updated_at": now_iso(),
        },
    )
    if verdict.passed:
        return ctx.ok(row_id)
    return ctx.skip(row_id, "gate_refused", verdict.reason)
