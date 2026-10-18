"""dedupe: the three duplicate classes, and the task that refuses two of them.

The task was reachable but never run end to end: it looked rows up through a
``fingerprint=`` / ``stem_key=`` selector that no task had registered, so every
row failed with ``unknown selector``. And the classifier never returned
``same_stem_same_key`` at all, so the middle bucket could not fire. These tests
run the real task over a real store and pin all three classes.
"""

from __future__ import annotations

from typing import Any

from conftest import make_question
from utmelab_bank.config import Config
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.task import run_task
from utmelab_bank.task.gates.dedupe import Dedupe


async def _dedupe(store: Store, config: Config, rows: list[dict[str, Any]]):
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", rows)
    return await run_task(Dedupe(), config, repo, where="all")


def _outcome(result, state: str) -> list[Any]:
    return [o for o in result.outcomes if o.state == state]


async def test_an_identical_repeat_is_refused(store: Store, config: Config) -> None:
    """Same stem, same options, same key: one row survives, the other is refused."""
    rows = [make_question(id="q_first"), make_question(id="q_second")]

    result = await _dedupe(store, config, rows)

    assert result.exit_code == 0
    assert len(_outcome(result, "ok")) == 1
    refused = _outcome(result, "skipped")
    assert len(refused) == 1
    assert refused[0].code == "duplicate_fingerprint"


async def test_same_stem_same_key_different_options_is_refused(
    store: Store, config: Config
) -> None:
    """The dangerous middle: the same questions restated, same letter still right."""
    rows = [
        make_question(id="q_first", stem="Which gas is noble and unreactive?", answer="A"),
        make_question(
            id="q_second",
            stem="Which gas is noble and unreactive?",
            options=["Helium", "Nitrogen", "Oxygen", "Hydrogen"],
            answer="A",
        ),
    ]

    result = await _dedupe(store, config, rows)

    assert result.exit_code == 0
    refused = _outcome(result, "skipped")
    assert len(refused) == 1
    assert refused[0].code == "duplicate_fingerprint"
    assert "answer" in (refused[0].detail or "")


async def test_same_stem_different_key_is_kept(store: Store, config: Config) -> None:
    """Two years' papers can share a stem and disagree on the answer. Both are real."""
    rows = [
        make_question(
            id="q_first",
            stem="Which gas is noble and unreactive?",
            options=["Argon", "Oxygen", "Iron", "Sodium"],
            answer="A",
        ),
        make_question(
            id="q_second",
            stem="Which gas is noble and unreactive?",
            options=["Helium", "Nitrogen", "Oxygen", "Hydrogen"],
            answer="B",
        ),
    ]

    result = await _dedupe(store, config, rows)

    assert result.exit_code == 0
    assert len(_outcome(result, "ok")) == 2
    assert _outcome(result, "skipped") == []


async def test_a_stem_holding_the_word_and_does_not_break_the_lookup(
    store: Store, config: Config
) -> None:
    """A stem key is data. " and " in a stem must not split it into two terms."""
    rows = [
        make_question(id="q_a", stem="A body moves north and then east. Find the distance."),
        make_question(
            id="q_b",
            stem="A body moves north and then east. Find the distance.",
            options=["5 m", "10 m", "13 m", "25 m"],
            answer="D",
        ),
    ]

    result = await _dedupe(store, config, rows)

    assert result.exit_code == 0
    assert result.run.failed == 0
