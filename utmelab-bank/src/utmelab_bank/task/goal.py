"""goal: compose proven tasks into one sequential run.

The goal is wiring, not a task: no task calls another task. The goal just
resolves each named task from the registry and runs them one after another,
sharing one config and one database.

Written last, once every unit is proven alone (README). A failed task stops
the goal; ``on_error`` decides whether a single failed row stops its step,
not the whole goal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from utmelab_bank.config import Config
from utmelab_bank.store.repository import Repository
from utmelab_bank.task.base import TaskResult, run_task
from utmelab_bank.task.base import get as get_task

__all__ = ["PRESETS", "Preset", "Step", "run_goal"]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step:
    """One step of the goal: a task name plus its selector options.

    ``where`` may carry a task-local override after a colon, e.g. ``gate:gated``
    or ``promote:all``; the colon is stripped and the right side used as that
    step's selector. The global ``--where`` is the default.
    """

    task: str
    where: str = "all"
    limit: int | None = None
    logical: str = "questions"


@dataclass(frozen=True)
class Preset:
    """A named composition whose steps carry their own tables and selectors.

    A preset is not a second engine: it is the same ``Step`` tuple an operator
    would type, kept in one place so a flow cannot drift out of order. The
    ``media`` preset is the whole figure path, including the check that makes a
    description usable.
    """

    steps: tuple[Step, ...]


PRESETS: dict[str, Preset] = {
    "media": Preset(
        steps=(
            Step(task="media-discover", where="has images", logical="questions"),
            Step(task="media-fetch", where="no blob", logical="media"),
            Step(task="ai-describe", where="no description", logical="media"),
            Step(task="media-verify", where="description unverified", logical="media"),
            Step(task="media-upload", where="description verified", logical="media"),
        )
    ),
}


async def run_goal(
    config: Config,
    repo: Repository,
    name: str,
    steps: tuple[Step, ...],
    *,
    dry_run: bool = False,
) -> tuple[TaskResult, ...]:
    """Run each step in sequence, returning one TaskResult per step.

    Raises :class:`TaskError` naming the first unknown task, so a goal that
    references a nonexistent task fails fast instead of running half of it.
    """
    results: list[TaskResult] = []
    for step in steps:
        plugin = get_task(step.task)  # TaskError: unknown task, named
        log.info("goal %s: step %s -> %s", name, step.task, step.where)
        result = await run_task(
            plugin,
            config,
            repo,
            logical=step.logical,
            where=step.where,
            limit=step.limit,
            dry_run=dry_run,
        )
        results.append(result)
    return tuple(results)
