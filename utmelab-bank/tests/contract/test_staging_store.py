"""Contract tests for the bank's own store."""

from datetime import UTC, datetime
from typing import Any, Optional

import pytest

from utmelab_bank.adapters.store import StagingStore
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.enums import PassageKind
from utmelab_bank.domain.models import (
    Content,
    Hashes,
    Option,
    Passage,
    Provenance,
    RichText,
    Scope,
    StagingItem,
)
from utmelab_bank.domain.state import InvalidTransition


NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows


class FakeClient:
    """A tiny in-memory table that answers the store's queries."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[Any, ...]] = {}
        self.passages: dict[str, tuple[Any, ...]] = {}
        self.statements: list[str] = []

    async def execute(
        self,
        statement: str,
        args: Optional[list[Any]] = None,
        *,
        commit: Optional[bool] = None,
    ) -> FakeResult:
        self.statements.append(statement)
        values = args or []
        if "INSERT OR REPLACE INTO passages" in statement:
            self.passages[values[0]] = tuple(values)
            return FakeResult([])
        if "SELECT id FROM passages" in statement:
            return FakeResult([(key,) for key in self.passages])
        if "FROM passages WHERE id" in statement:
            row = self.passages.get(values[0])
            return FakeResult([row] if row else [])
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

    async def commit(self) -> None:
        """The client contract has a commit, so the fake does too."""
        return None



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


def make_passage() -> Passage:
    return Passage(
        id="psg_1",
        exam="JAMB",
        subject="use-of-english",
        year=2025,
        kind=PassageKind.COMPREHENSION,
        title="Passage A",
        text=RichText(text="Adura had learned to read the room."),
    )


async def test_a_passage_is_written_to_its_own_table() -> None:
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()

    item = make_item().model_copy(
        update={
            "content": make_item().content.model_copy(update={"passage_id": "psg_1"}),
            "passage": make_passage(),
        }
    )
    await store.save(item)

    assert "psg_1" in client.passages
    assert await store.passage_ids() == frozenset({"psg_1"})


async def test_a_passage_round_trips_by_id() -> None:
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()

    item = make_item().model_copy(
        update={
            "content": make_item().content.model_copy(update={"passage_id": "psg_1"}),
            "passage": make_passage(),
        }
    )
    await store.save(item)

    back = await store.load_passage("psg_1")

    assert back is not None
    assert back.id == "psg_1"
    assert back.kind is PassageKind.COMPREHENSION
    assert back.subject == "use-of-english"
    assert back.text.text == "Adura had learned to read the room."


async def test_two_questions_share_one_passage_row() -> None:
    """A passage is shared, so it is one row keyed by its id."""
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()

    first = make_item()
    second = first.model_copy(
        update={
            "id": "live:q2",
            "provenance": first.provenance.model_copy(update={"source_item_id": "q2"}),
        }
    )
    for item in (first, second):
        await store.save(
            item.model_copy(
                update={
                    "content": item.content.model_copy(update={"passage_id": "psg_1"}),
                    "passage": make_passage(),
                }
            )
        )

    assert len(client.passages) == 1
    assert await store.passage_ids() == frozenset({"psg_1"})


async def test_a_missing_passage_reads_as_none() -> None:
    client = FakeClient()
    store = StagingStore(client)
    await store.prepare()

    assert await store.load_passage("nope") is None
