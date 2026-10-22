"""Contract tests for the content index and the dedupe step."""

import json
from datetime import UTC, datetime
from typing import Any

from utmelab_bank.adapters.dedupe_service import DedupeService
from utmelab_bank.adapters.index_refresh import IndexRefresher
from utmelab_bank.adapters.production import ProductionContentReader
from utmelab_bank.adapters.store.index import BANK, PRODUCTION, ContentIndexStore
from utmelab_bank.domain.dedupe import (
    duplicate_content_key,
    duplicate_near_key,
    near_duplicate_fingerprint,
)
from utmelab_bank.domain.enums import InlineKind, State
from utmelab_bank.domain.models import (
    Content,
    Hashes,
    Inline,
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
        if "WHERE content_hash = ? OR near_duplicate = ?" in statement:
            exact = [r for r in self.rows if r[0] == values[0]]
            near = [r for r in self.rows if r[1] == values[1]]
            if exact:
                return FakeResult([(exact[0][3], exact[0][0])])
            if near:
                return FakeResult([(near[0][3], near[0][0])])
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
    year: int = 2025,
    image: str | None = None,
    state: State = State.GATED,
) -> StagingItem:
    provenance = Provenance(
        source="live",
        source_url="https://example.com/q1",
        source_item_id=item_id.split(":")[-1],
        fetched_at=NOW,
        payload_hash="b" * 64,
        source_version="1",
        scope=Scope(exam="JAMB", subject="mathematics", year=year),
    )
    inline = (
        (
            Inline(
                kind=InlineKind.IMAGE,
                start=len(stem),
                len=0,
                url=image,
                position="below",
            ),
        )
        if image
        else ()
    )
    content = Content(
        stem=RichText(text=stem, inline=inline),
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


def image_keys_of(item: StagingItem) -> tuple[str, ...]:
    keys: list[str] = []
    texts = [item.content.stem, *(option.text for option in item.content.options)]
    for text in texts:
        for inline in text.inline:
            if inline.kind is InlineKind.IMAGE:
                keys.append(f"{inline.url}|{inline.position}|{inline.alt or ''}")
    return tuple(keys)


def fingerprint_of(item: StagingItem) -> str:
    return near_duplicate_fingerprint(
        item.content.stem.text,
        tuple(option.text.text for option in item.content.options),
        image_keys_of(item),
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
        content_hash=service.content_key(item),
        near_duplicate=service.near_key(item),
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
        content_hash=duplicate_content_key("e" * 64, original.provenance.scope.year),
        near_duplicate=service.near_key(original),
        origin=PRODUCTION,
        question_id="q_existing",
    )
    shuffled = make_item(item_id="live:q2", stem="What is 2 + 2?", options=("6", "5", "4", "3"))

    refused = await service.apply(shuffled)

    assert refused.state is State.REJECTED
    assert refused.error is not None
    assert "near" in refused.error


async def test_the_same_content_in_a_different_year_is_not_a_duplicate() -> None:
    """A question can be reused by a later paper; that is a second row."""
    service = DedupeService(ContentIndexStore(FakeClient()))
    first = make_item(year=2025)
    await service.remember(first, origin=BANK)
    later = make_item(item_id="live:q2", year=2026)

    moved = await service.apply(later)

    assert moved.state is State.DEDUPED
    assert moved.error is None


async def test_the_same_content_in_the_same_year_is_a_duplicate() -> None:
    service = DedupeService(ContentIndexStore(FakeClient()))
    first = make_item(year=2025)
    await service.remember(first, origin=BANK)
    twin = make_item(item_id="live:q2", year=2025)

    refused = await service.apply(twin)

    assert refused.state is State.REJECTED
    assert refused.error is not None
    assert "exact" in refused.error


async def test_a_different_image_makes_the_near_fingerprint_differ() -> None:
    """Words alone are not the question; the figure is part of it too."""
    service = DedupeService(ContentIndexStore(FakeClient()))
    first = make_item(image="figure-a.png")
    second = make_item(item_id="live:q2", image="figure-b.png")

    assert service.fingerprint(first) != service.fingerprint(second)
    assert service.near_key(first) != service.near_key(second)


async def test_the_same_image_keeps_the_near_fingerprint() -> None:
    service = DedupeService(ContentIndexStore(FakeClient()))
    first = make_item(image="figure-a.png")
    second = make_item(item_id="live:q2", image="figure-a.png")

    assert service.fingerprint(first) == service.fingerprint(second)


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


OPTIONS = json.dumps(
    [
        {"id": "a", "text": {"text": "3", "inline": []}},
        {"id": "b", "text": {"text": "4", "inline": []}},
    ]
)

NEAR = near_duplicate_fingerprint("What is 2 + 2?", ("3", "4"))


def production_row(
    question_id: str = "q1",
    *,
    year: int = 2025,
    content_hash: str = HASH,
    stem_inline: str = "[]",
    options: str = OPTIONS,
) -> tuple[Any, ...]:
    return (question_id, year, content_hash, "What is 2 + 2?", stem_inline, options)


async def test_the_reader_computes_the_near_duplicate_fingerprint() -> None:
    reader = ProductionContentReader(ProductionClient([production_row()]))

    known = await reader.known()

    assert len(known) == 1
    assert known[0].question_id == "q1"
    assert known[0].year == 2025
    assert known[0].content_hash == duplicate_content_key(HASH, 2025)
    assert known[0].near_duplicate == duplicate_near_key(NEAR, 2025)


async def test_the_reader_puts_the_image_in_the_near_key() -> None:
    image = json.dumps([{"kind": "image", "start": 0, "len": 0, "url": "fig.png"}])
    reader = ProductionContentReader(ProductionClient([production_row(stem_inline=image)]))

    known = await reader.known()

    near = near_duplicate_fingerprint("What is 2 + 2?", ("3", "4"), ("fig.png||",))
    assert known[0].near_duplicate == duplicate_near_key(near, 2025)


async def test_the_reader_keeps_the_same_content_in_two_years() -> None:
    reader = ProductionContentReader(
        ProductionClient([production_row("q1", year=2025), production_row("q2", year=2026)])
    )

    known = await reader.known()

    assert len(known) == 2
    assert known[0].content_hash != known[1].content_hash
    assert known[0].content_hash == duplicate_content_key(HASH, 2025)
    assert known[1].content_hash == duplicate_content_key(HASH, 2026)


async def test_the_refresh_loads_production_into_the_index() -> None:
    reader = ProductionContentReader(ProductionClient([production_row()]))
    index = ContentIndexStore(FakeClient())
    refresher = IndexRefresher(index, reader)

    count = await refresher.refresh()

    assert count == 1
    assert await index.count(PRODUCTION) == 1
    found = await index.find(
        content_hash=duplicate_content_key(HASH, 2025),
        near_duplicate=duplicate_near_key(NEAR, 2025),
    )
    assert found is not None
    assert found.question_id == "q1"


async def test_the_refresh_drops_what_production_deleted() -> None:
    """A question production has removed must stop being a duplicate."""
    client = FakeClient()
    index = ContentIndexStore(client)
    reader = ProductionContentReader(ProductionClient([production_row()]))
    await IndexRefresher(index, reader).refresh()
    assert await index.count(PRODUCTION) == 1

    await IndexRefresher(index, ProductionContentReader(ProductionClient([]))).refresh()

    assert await index.count(PRODUCTION) == 0
