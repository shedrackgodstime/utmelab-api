"""Contract tests for the content index and the dedupe step."""

import json
from datetime import UTC, datetime
from typing import Any

from utmelab_bank.adapters.dedupe_service import DedupeService
from utmelab_bank.adapters.index_refresh import IndexRefresher
from utmelab_bank.adapters.production import ProductionContentReader
from utmelab_bank.adapters.store.index import BANK, PRODUCTION, ContentIndexStore
from utmelab_bank.domain.dedupe import near_duplicate_fingerprint
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import (
    Content,
    Hashes,
    Option,
    Provenance,
    RichText,
    Scope,
    StagingItem,
)

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
HASH = "c" * 64


class FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows


class FakeClient:
    """A tiny in-memory table that answers the index's queries."""

    def __init__(self) -> None:
        self.rows: list[tuple[Any, ...]] = []
        self.statements: list[str] = []

    async def execute(
        self,
        statement: str,
        args: list[Any] | None = None,
        *,
        commit: bool | None = None,
    ) -> FakeResult:
        self.statements.append(statement)
        values = args or []
        if "INSERT OR REPLACE INTO content_index" in statement:
            self.rows.append(tuple(values))
            return FakeResult([])
        if "DELETE FROM content_index" in statement:
            self.rows = [r for r in self.rows if r[2] != values[0]]
            return FakeResult([])
        if "WHERE content_hash = ? LIMIT 1" in statement:
            found = [r for r in self.rows if r[0] == values[0]]
            return FakeResult([(found[0][3],)] if found else [])
        if "WHERE near_duplicate = ?" in statement:
            found = [r for r in self.rows if r[1] == values[0]]
            return FakeResult([(r[3],) for r in found])
        if "count(*) FROM content_index" in statement:
            if values:
                return FakeResult([(len([r for r in self.rows if r[2] == values[0]]),)])
            return FakeResult([(len(self.rows),)])
        return FakeResult([])

    async def commit(self) -> None:
        """The client contract has a commit, so the fake does too."""
        return None


def make_item(
    *,
    item_id: str = "live:q1",
    stem: str = "What is 2 + 2?",
    options: tuple[str, ...] = ("3", "4", "5", "6"),
    answer: str = "b",
    state: State = State.GATED,
) -> StagingItem:
    provenance = Provenance(
        source="live",
        source_url="https://example.com/q1",
        source_item_id=item_id.split(":")[-1],
        fetched_at=NOW,
        payload_hash="b" * 64,
        source_version="1",
        scope=Scope(exam="JAMB", subject="mathematics", year=2025),
    )
    content = Content(
        stem=RichText(text=stem),
        options=tuple(
            Option(id=chr(ord("a") + index), text=RichText(text=text))
            for index, text in enumerate(options)
        ),
        answer=answer,
        marks=1.0,
    )
    return StagingItem(
        id=item_id,
        provenance=provenance,
        content=content,
        state=state,
        hashes=Hashes(payload_hash="b" * 64, content_hash=HASH, bundle_hash="d" * 64),
        created_at=NOW,
        updated_at=NOW,
    )


def fingerprint_of(item: StagingItem) -> str:
    return near_duplicate_fingerprint(
        item.content.stem.text,
        tuple(option.text.text for option in item.content.options),
    )


# ── the index ───────────────────────────────────────────────────────────────


async def test_the_index_remembers_and_finds_an_exact_match() -> None:
    index = ContentIndexStore(FakeClient())
    await index.remember(
        content_hash=HASH,
        near_duplicate="abc",
        origin=PRODUCTION,
        question_id="q1",
    )

    found = await index.find(content_hash=HASH, near_duplicate="nothing")

    assert found is not None
    assert found.kind == "exact"
    assert found.question_id == "q1"


async def test_the_index_finds_a_near_match() -> None:
    index = ContentIndexStore(FakeClient())
    await index.remember(
        content_hash="other", near_duplicate="abc", origin=PRODUCTION, question_id="q1"
    )

    found = await index.find(content_hash=HASH, near_duplicate="abc")

    assert found is not None
    assert found.kind == "near"
    assert found.question_id == "q1"


async def test_the_exact_match_wins_over_the_near_one() -> None:
    """A reviewer should be told the stronger finding first."""
    index = ContentIndexStore(FakeClient())
    await index.remember(
        content_hash=HASH, near_duplicate="abc", origin=PRODUCTION, question_id="q1"
    )
    await index.remember(
        content_hash="other", near_duplicate="abc", origin=PRODUCTION, question_id="q2"
    )

    found = await index.find(content_hash=HASH, near_duplicate="abc")

    assert found is not None
    assert found.kind == "exact"


async def test_an_unknown_content_is_not_a_duplicate() -> None:
    index = ContentIndexStore(FakeClient())

    assert await index.find(content_hash=HASH, near_duplicate="abc") is None


async def test_forgetting_an_origin_drops_only_that_origin() -> None:
    client = FakeClient()
    index = ContentIndexStore(client)
    await index.remember(content_hash=HASH, near_duplicate="a", origin=PRODUCTION, question_id="q1")
    await index.remember(content_hash="d" * 64, near_duplicate="b", origin=BANK, question_id="q2")

    await index.forget(PRODUCTION)

    assert await index.count() == 1
    assert await index.count(BANK) == 1
    assert await index.count(PRODUCTION) == 0


# ── the dedupe step ─────────────────────────────────────────────────────────


async def test_a_new_item_moves_to_deduped() -> None:
    service = DedupeService(ContentIndexStore(FakeClient()))

    moved = await service.apply(make_item())

    assert moved.state is State.DEDUPED
    assert moved.error is None


async def test_a_duplicate_is_refused_with_the_id_it_duplicates() -> None:
    client = FakeClient()
    index = ContentIndexStore(client)
    service = DedupeService(index)
    item = make_item()
    await index.remember(
        content_hash=HASH,
        near_duplicate=fingerprint_of(item),
        origin=PRODUCTION,
        question_id="q_existing",
    )

    refused = await service.apply(item)

    assert refused.state is State.REJECTED
    assert refused.error is not None
    assert "q_existing" in refused.error


async def test_a_shuffled_duplicate_is_refused() -> None:
    """The same question with the options in a different order.

    This is the duplicate the near-duplicate rule is for. The exact hash
    would never see it, because the content is not the same.
    """
    client = FakeClient()
    index = ContentIndexStore(client)
    service = DedupeService(index)
    original = make_item(stem="What is 2 + 2?")
    await index.remember(
        content_hash="e" * 64,
        near_duplicate=fingerprint_of(original),
        origin=PRODUCTION,
        question_id="q_existing",
    )
    shuffled = make_item(item_id="live:q2", stem="What is 2 + 2?", options=("6", "5", "4", "3"))

    refused = await service.apply(shuffled)

    assert refused.state is State.REJECTED
    assert refused.error is not None
    assert "near" in refused.error


async def test_remembering_an_item_makes_the_next_one_a_duplicate() -> None:
    client = FakeClient()
    service = DedupeService(ContentIndexStore(client))
    first = make_item()

    await service.remember(first, origin=BANK)
    second = make_item(item_id="live:q2")

    refused = await service.apply(second)

    assert refused.state is State.REJECTED


# ── the production reader and the refresh ───────────────────────────────────


class ProductionClient:
    """Answers the one query the content reader makes."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    async def execute(
        self,
        statement: str,
        args: list[Any] | None = None,
        *,
        commit: bool | None = None,
    ) -> FakeResult:
        return FakeResult(self.rows)


async def test_the_reader_computes_the_near_duplicate_fingerprint() -> None:
    options = json.dumps(
        [
            {"id": "a", "text": {"text": "3", "inline": []}},
            {"id": "b", "text": {"text": "4", "inline": []}},
        ]
    )
    reader = ProductionContentReader(ProductionClient([("q1", HASH, "What is 2 + 2?", options)]))

    known = await reader.known()

    assert len(known) == 1
    assert known[0].question_id == "q1"
    assert known[0].content_hash == HASH
    assert known[0].near_duplicate == near_duplicate_fingerprint("What is 2 + 2?", ("3", "4"))


async def test_the_refresh_loads_production_into_the_index() -> None:
    options = json.dumps(
        [
            {"id": "a", "text": {"text": "3", "inline": []}},
            {"id": "b", "text": {"text": "4", "inline": []}},
        ]
    )
    reader = ProductionContentReader(ProductionClient([("q1", HASH, "What is 2 + 2?", options)]))
    index = ContentIndexStore(FakeClient())
    refresher = IndexRefresher(index, reader)

    count = await refresher.refresh()

    assert count == 1
    assert await index.count(PRODUCTION) == 1
    found = await index.find(
        content_hash=HASH,
        near_duplicate=near_duplicate_fingerprint("What is 2 + 2?", ("3", "4")),
    )
    assert found is not None
    assert found.question_id == "q1"


async def test_the_refresh_drops_what_production_deleted() -> None:
    """A question production has removed must stop being a duplicate."""
    client = FakeClient()
    index = ContentIndexStore(client)
    options = json.dumps([{"id": "a", "text": {"text": "3", "inline": []}}])
    reader = ProductionContentReader(ProductionClient([("q1", HASH, "What is 2 + 2?", options)]))
    await IndexRefresher(index, reader).refresh()
    assert await index.count(PRODUCTION) == 1

    await IndexRefresher(index, ProductionContentReader(ProductionClient([]))).refresh()

    assert await index.count(PRODUCTION) == 0
