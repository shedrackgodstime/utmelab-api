"""The run record, and the per-row envelope every task writes through.

A run is one execution of one task against one target. It is the audit trail
for the whole package, so it records what was asked for, what happened, and
what failed, in a shape a workflow can read without parsing prose.

The row envelope is why no task needs its own error handling. A task calls
``ctx.ok`` or ``ctx.fail`` and the base class owns the retry policy, the backoff
and the exit code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from utmelab_bank.model.base import BankModel, now_iso

__all__ = ["Run", "RowState", "Lane", "RowOutcome"]

Lane = Literal["raw", "work", "ready"]
RowState = Literal["ok", "skipped", "failed", "pending"]


class Run(BankModel):
    """One task execution. Written at the start, updated at the end.

    Not frozen, unlike most models here: it is the live tally of a run in
    progress, and the base class folds each row's outcome into it as it goes.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    id: str
    task: str = Field(min_length=1, max_length=80)
    target: Lane = "work"
    selector: str = "all"

    sink: Literal["db", "json"] = "db"
    status: Literal["running", "done", "stopped", "broken"] = "running"

    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0

    started_at: str = Field(default_factory=now_iso)
    finished_at: str | None = None
    detail: str | None = None

    def counts(self, outcome: RowOutcome) -> None:
        """Fold one row's outcome into the run totals."""
        self.total += 1
        match outcome.state:
            case "ok":
                self.succeeded += 1
            case "skipped":
                self.skipped += 1
            case _:
                self.failed += 1


class RowOutcome(BankModel):
    """What one row did. Written by the task base, not by the task."""

    row_id: str
    state: RowState = "ok"
    code: str | None = None
    detail: str | None = None
    retryable: bool = False

    @property
    def ok(self) -> bool:
        return self.state == "ok"
