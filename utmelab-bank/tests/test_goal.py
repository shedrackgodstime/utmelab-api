"""goal: composed tasks run in sequence, unknown tasks refuse."""

from __future__ import annotations

import pytest

from utmelab_bank.config import Config
from utmelab_bank.errors import TaskError
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.task.goal import Step, run_goal


async def test_goal_runs_steps_in_sequence(store: Store, config: Config) -> None:
    """Each step runs once, in order, sharing one repo."""
    repo = Repository(store, lane="work")
    results = await run_goal(
        config,
        repo,
        "smoke",
        (
            Step(task="gate", where="all"),
            Step(task="dedupe", where="all"),
        ),
    )
    assert [r.run.task for r in results] == ["gate", "dedupe"]
    assert all(r.exit_code == 0 for r in results)


async def test_goal_unknown_task_refuses(store: Store, config: Config) -> None:
    """A goal that names a nonexistent task fails fast, naming it."""
    repo = Repository(store, lane="work")
    with pytest.raises(TaskError, match="unknown task"):
        await run_goal(
            config,
            repo,
            "bad",
            (Step(task="no-such-task", where="all"),),
        )


async def test_goal_empty_steps_returns_empty(store: Store, config: Config) -> None:
    repo = Repository(store, lane="work")
    results = await run_goal(config, repo, "empty", ())
    assert results == ()


async def test_goal_step_where_override(store: Store, config: Config) -> None:
    """Each step keeps its own where; the default applies when omitted."""
    repo = Repository(store, lane="work")
    results = await run_goal(
        config,
        repo,
        "mixed",
        (
            Step(task="gate", where="gated"),
            Step(task="dedupe", where="all"),
        ),
    )
    assert results[0].run.selector == "gated"
    assert results[1].run.selector == "all"
