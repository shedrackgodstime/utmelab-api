"""Gates, model tasks, media tasks and promotion.

Importing this package registers every task, which is what lets the CLI dispatch
a name without knowing which module a task lives in. A new task is one module
and one import line here.
"""

from __future__ import annotations

from utmelab_bank.task.base import (
    Task,
    TaskContext,
    TaskResult,
    all_tasks,
    declares_rows_in,
    get,
    registered,
    run_task,
)
from utmelab_bank.task import gates  # noqa: F401  registers the gates
from utmelab_bank.task import intake as intake_task  # noqa: F401  registers intake
from utmelab_bank.task import promote as promote_task  # noqa: F401  registers promotion

__all__ = [
    "Task",
    "TaskContext",
    "TaskResult",
    "all_tasks",
    "declares_rows_in",
    "get",
    "registered",
    "run_task",
]
