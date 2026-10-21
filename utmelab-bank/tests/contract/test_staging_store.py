"""Contract tests for the bank's own store."""

import json
from datetime import UTC, datetime
from typing import Any, Optional

import pytest

from utmelab_pipeline.adapters.store import StagingStore
from utmelab_pipeline.domain.enums import State
from utmelab_pipeline.domain.models import (
    Content,
    Hashes,
    Option,
    Provenance,
    RichText,
    Scope,
    StagingItem,
)
from utmelab_pipeline.domain.state import InvalidTransition


NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows


class FakeClient:
    """A tiny in-memory table that answers the store's queries."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[Any, ...]] = {}
        self.statements: list[str] = []

    async def execute(
        self, statement: str, args: Optional[list[Any]] = None
    ) -> FakeResult:
        self.statements.append(statement)
        values = args or []
        if "INSERT OR REPLACE" in statement:
            self.rows[values[0]] = tuple(values)
            return FakeResult([])
        if "WHERE state = ?" in statement:
            state, limit = values
            found = [r for r in self.rows.values() if r[1] == state][:limit]
            return FakeResult(found)
        if "SELECT id, state" in statement:
            key = values[0]
            row = self.rows.get(key)
            return FakeResult([row] if row else [])
        return FakeResult([])


def make_item(state: State = State.CATALOGUED) -> StagingItem:
    provenance = Provenance(
        source="live",
        source_url="https://example.com/q1",
        source_item_id="q1",
        fetched_at=NOW,
        payload_hash="b" * 64,
        source_version="1",
        scope=Scope(exam="JAMB", subject="biology", year=2024),
    )
    content = Content(
        stem=RichText(text="Which organelle is the site of aerobic respiration?"),
        options=(
            Option(id="A", text=RichText(text="Nucleus")),
            Option(id="B", text=RichText(text="Mitochondrion")),
        ),
        answer="B",
        marks=2.5,
    )
    return StagingItem(
        id=provenance.external_key,
        provenance=provenance,
        content=content,
        state=state,
        hashes=Hashes(
            payload_hash="b" * 64,
            content_hash="c" * 64,
            bundle_hash="d" * 64,
        ),
        created_at=NOW,
        updated_at=NOW,
    )


async def test_prepare_creates_the_one_table() -> None:
    client = FakeClient()
    await StagingStore(client).prepare()
    assert any("staging_items" in s for s in client.statements)


async def test_save_then_load_round_trips() -> None:
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()

    item = make_item()
    await store.save(item)

    back = await store.load(item.id)
    assert back is not None
    assert back.id == item.id
    assert back.content.answer == "B"
    assert back.content.stem.text == item.content.stem.text
    assert back.state is State.CATALOGUED
    assert back.hashes is not None
    assert back.hashes.content_hash == "c" * 64


async def test_load_returns_none_for_a_missing_row() -> None:
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()
    assert await store.load("nope") is None


async def test_transition_moves_the_row() -> None:
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()
    item = make_item()
    await store.save(item)

    moved = await store.transition(item.id, "catalogued", "enriched")
    assert moved.state is State.ENRICHED

    back = await store.load(item.id)
    assert back is not None
    assert back.state is State.ENRICHED


async def test_transition_refuses_the_wrong_expected_state() -> None:
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()
    item = make_item()
    await store.save(item)

    with pytest.raises(InvalidTransition):
        await store.transition(item.id, "adapted", "enriched")


async def test_transition_refuses_an_invented_move() -> None:
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()
    item = make_item()
    await store.save(item)

    with pytest.raises(InvalidTransition):
        await store.transition(item.id, "catalogued", "ready")


async def test_transition_refuses_a_missing_row() -> None:
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()
    with pytest.raises(KeyError):
        await store.transition("nope", "catalogued", "enriched")


async def test_list_by_state_returns_only_that_state() -> None:
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()
    item = make_item()
    await store.save(item)

    enriched = await store.list_by_state("enriched")
    assert enriched == ()

    await store.transition(item.id, "catalogued", "enriched")
    rows = await store.list_by_state("enriched")
    assert [row.id for row in rows] == [item.id]
