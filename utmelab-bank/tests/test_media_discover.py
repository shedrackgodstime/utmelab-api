"""media-discover: record a provider figure once, and never record our own copy.

The media goal can run after a previous upload. At that point a question carries
``/media/ab/<sha>.png``, which is our path, not a provider url. A discover that
treats every image mark as a new figure creates a duplicate row for every
published figure on the next pass. These tests pin the identity to the source
url.
"""

from __future__ import annotations

import hashlib
from typing import Any

from utmelab_bank.config import Config
from utmelab_bank.model.richtext import Mark
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.task.base import run_task
from utmelab_bank.task.gates.media_presence import MediaPresence

SOURCE = "https://cdn.example/figure.png"
OUR_PATH = "/media/ab/abcdef.png"


def _mark(url: str) -> Mark:
    return Mark(kind="image", start=0, len=0, url=url, position="above")


def _id_for(url: str) -> str:
    return f"m_{hashlib.sha256(url.encode('utf-8')).hexdigest()[:32]}"


async def test_discover_records_a_provider_figure_once(
    store: Store,
    config: Config,
    make_rows: Any,
) -> None:
    repo = Repository(store, lane="work")
    question = make_rows(1, marks=[_mark(SOURCE)])[0]
    await repo.insert_many("questions", [question])

    first = await run_task(MediaPresence(), config, repo, logical="questions")
    assert first.run.succeeded == 1

    rows = await repo.rows("media", "all")
    assert len(rows) == 1
    assert rows[0]["id"] == _id_for(SOURCE)
    assert rows[0]["source_url"] == SOURCE
    assert rows[0]["question_id"] == question["id"]

    second = await run_task(MediaPresence(), config, repo, logical="questions")
    assert second.run.skipped == 1
    assert second.outcomes[0].code == "already_discovered"
    assert len(await repo.rows("media", "all")) == 1


async def test_discover_ignores_a_figure_already_on_our_path(
    store: Store,
    config: Config,
    make_rows: Any,
) -> None:
    repo = Repository(store, lane="work")
    question = make_rows(1, marks=[_mark(OUR_PATH)])[0]
    await repo.insert_many("questions", [question])

    result = await run_task(MediaPresence(), config, repo, logical="questions")

    assert result.run.succeeded == 1
    assert await repo.rows("media", "all") == []


async def test_discover_does_not_duplicate_a_figure_recorded_under_another_id(
    store: Store,
    config: Config,
    make_rows: Any,
    media_rows: list[dict[str, Any]],
) -> None:
    """A changed id scheme must not make a recorded figure look new."""
    repo = Repository(store, lane="work")
    question = make_rows(1, marks=[_mark(SOURCE)])[0]
    await repo.insert_many("questions", [question])

    legacy = media_rows[0]
    legacy.update({"id": "m_legacy", "source_url": SOURCE, "question_id": question["id"]})
    await repo.insert_many("media", [legacy])

    result = await run_task(MediaPresence(), config, repo, logical="questions")

    assert result.run.skipped == 1
    rows = await repo.rows("media", "all")
    assert [row["id"] for row in rows] == ["m_legacy"]
