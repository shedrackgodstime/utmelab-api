"""Gates, model tasks, media tasks and promotion.

Importing this package registers every task, which is what lets the CLI dispatch
a name without knowing which module a task lives in. A new task is one module
and one import line here.
"""

from __future__ import annotations

from utmelab_bank.task import gates  # noqa: F401  registers the gates
from utmelab_bank.task import intake as intake_task  # noqa: F401  registers intake
from utmelab_bank.task import media as media_task  # noqa: F401  registers media tasks
from utmelab_bank.task import promote as promote_task  # noqa: F401  registers promotion
from utmelab_bank.task.ai import describe as ai_describe_task  # noqa: F401  registers ai-describe
from utmelab_bank.task.ai import explain as ai_explain_task  # noqa: F401  registers ai-explain
from utmelab_bank.task.ai import media_verify as ai_media_verify_task  # noqa: F401  registers media-verify
from utmelab_bank.task.ai import tag as ai_tag_task  # noqa: F401  registers ai-tag
from utmelab_bank.task.ai import verify as ai_verify_task  # noqa: F401  registers ai-verify
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
