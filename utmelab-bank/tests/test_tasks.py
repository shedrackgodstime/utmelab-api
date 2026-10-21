"""The task runner, proved end to end without a network or a model."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

from utmelab_bank.adapters.media import (
    DescribeImageConsensus,
    MediaIngestor,
    MediaService,
    PillowMediaValidator,
)
from utmelab_bank.adapters.production import KnownQuestion
from utmelab_bank.adapters.providers.mock import MockProvider
from utmelab_bank.adapters.sources.fixture import FixtureSource
from utmelab_bank.config import Settings
from utmelab_bank.domain.dedupe import Duplicate
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import (
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
    Producer,
    StagingItem,
)
from utmelab_bank.runtime import Runtime
from utmelab_bank.tasks import (
    TaskOptions,
    explain,
    fetch,
    index,
    media,
    ready,
    review,
    run_preset,
    status,
    tag,
)

from .media_fakes import FakeMediaFetcher, FakeMediaStore

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sources" / "fixture"
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
OPTIONS = TaskOptions(exam="JAMB", subject="Biology", year=2024, section="A")


def make_catalog() -> CatalogSnapshot:
    return CatalogSnapshot(
        version="2026.1",
        exam="JAMB",
        subject="Biology",
        topics=(
            CatalogTopic(
                id="cell-biology",
                slug="cell-biology",
                name="Cell biology",
            ),
        ),
        subtopics=(
            CatalogSubtopic(
                id="cell-structure",
                slug="cell-structure",
                name="Cell structure",
                topic_id="cell-biology",
            ),
        ),
    )


class FakeStaging:
    """The staging surface a task uses, in memory."""

    def __init__(self) -> None:
        self.items: dict[str, StagingItem] = {}

    async def prepare(self) -> None:
        return None

    async def save(self, item: StagingItem) -> None:
        self.items[item.id] = item

    async def load(self, item_id: str) -> StagingItem | None:
        return self.items.get(item_id)

    async def passage_ids(self) -> frozenset[str]:
        return frozenset(
            item.passage.id for item in self.items.values() if item.passage is not None
        )

    async def list_by_state(self, state: str, *, limit: int = 100) -> tuple[StagingItem, ...]:
        return await self.list_by_states((state,), limit=limit)

    async def list_by_states(
        self,
        states: Sequence[str],
        *,
        limit: int = 100,
        exam: str | None = None,
        subject: str | None = None,
        year: int | None = None,
    ) -> tuple[StagingItem, ...]:
        wanted = set(states)
        rows = [
            item
            for item in sorted(self.items.values(), key=lambda one: one.created_at)
            if item.state.value in wanted
            and (exam is None or item.provenance.scope.exam == exam)
            and (subject is None or item.provenance.scope.subject == subject)
            and (year is None or item.provenance.scope.year == year)
        ]
        return tuple(rows[:limit])

    async def counts_by_state(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items.values():
            counts[item.state.value] = counts.get(item.state.value, 0) + 1
        return counts


class FakeIndex:
    """The content index, in memory. Exact matches only, which is enough."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    async def remember(
        self,
        *,
        content_hash: str,
        near_duplicate: str,
        origin: str,
        question_id: str,
    ) -> None:
        self.rows.append((content_hash, near_duplicate, origin, question_id))

    async def remember_many(
        self,
        entries: Sequence[tuple[str, str, str, str]],
        *,
        commit: bool = True,
    ) -> None:
        self.rows.extend(entries)

    async def forget(self, origin: str) -> None:
        self.rows = [row for row in self.rows if row[2] != origin]

    async def exact_match(self, content_hash: str) -> str | None:
        for row in self.rows:
            if row[0] == content_hash:
                return row[3]
        return None

    async def near_matches(self, near_duplicate: str) -> tuple[str, ...]:
        return tuple(row[3] for row in self.rows if row[1] == near_duplicate)

    async def find(self, *, content_hash: str, near_duplicate: str) -> Duplicate | None:
        exact = await self.exact_match(content_hash)
        if exact is not None:
            return Duplicate(kind="exact", question_id=exact)
        near = await self.near_matches(near_duplicate)
        if near:
            return Duplicate(kind="near", question_id=near[0])
        return None

    async def commit(self) -> None:
        return None

    async def count(self, origin: str | None = None) -> int:
        if origin is None:
            return len(self.rows)
        return sum(1 for row in self.rows if row[2] == origin)


class FakeCatalog:
    def __init__(self, catalog: CatalogSnapshot) -> None:
        self.catalog = catalog

    async def snapshot(self, exam: str, subject: str) -> CatalogSnapshot:
        assert (exam, subject) == (self.catalog.exam, self.catalog.subject)
        return self.catalog


class FakeProduction:
    def __init__(self, questions: Sequence[KnownQuestion] = ()) -> None:
        self.questions = tuple(questions)

    async def iter_known(self) -> AsyncIterator[KnownQuestion]:
        for question in self.questions:
            yield question


def make_runtime(
    *,
    index: FakeIndex | None = None,
    production: FakeProduction | None = None,
    source: bool = True,
    media_branch: bool = True,
) -> tuple[Runtime, FakeStaging, FakeMediaFetcher]:
    provider = MockProvider()
    fetcher = FakeMediaFetcher()
    ingestor = MediaIngestor(fetcher, PillowMediaValidator(), FakeMediaStore())
    describer = DescribeImageConsensus(
        (
            MockProvider(),
            MockProvider(producer=Producer(provider="mock", model="mock-v2")),
        )
    )
    staging = FakeStaging()
    runtime = Runtime(
        settings=Settings(
            prod_database_url="https://prod.invalid",
            prod_auth_token="prod-token",
            bank_database_url="https://bank.invalid",
            bank_auth_token="bank-token",
        ),
        staging=staging,
        index=index or FakeIndex(),
        catalog_reader=FakeCatalog(make_catalog()),
        production=production or FakeProduction(),
        source=FixtureSource(FIXTURE_DIR) if source else None,
        tagger=provider,
        explainer=provider,
        verifier=provider,
        ingestor=ingestor if media_branch else None,
        media=(MediaService(ingestor, describer) if media_branch else None),
    )
    return runtime, staging, fetcher


async def test_fetch_through_ready() -> None:
    runtime, staging, fetcher = make_runtime()

    fetched = await fetch(runtime, OPTIONS)
    assert fetched.ok, fetched.errors
    assert fetched.done == 1
    row = next(iter(staging.items.values()))
    assert row.state is State.DEDUPED
    assert row.media_refs == ()
    assert len(row.media_assets) == 1
    assert row.media_assets[0].source_url is None
    assert row.content.stem.inline[0].url == row.media_assets[0].storage_url
    assert len(fetcher.urls) == 1

    tagged = await tag(runtime, OPTIONS)
    assert tagged.ok, tagged.errors
    row = await staging.load(row.id)
    assert row is not None
    assert row.state is State.CATALOGUED
    assert row.catalog is not None

    # The figure is captured but not described yet: explain must not race it.
    guarded = await explain(runtime, OPTIONS)
    assert guarded.skipped == 1
    assert guarded.done == 0
    row = await staging.load(row.id)
    assert row is not None
    assert row.state is State.CATALOGUED

    described = await media(runtime, OPTIONS)
    assert described.ok, described.errors
    assert described.done == 1
    row = await staging.load(row.id)
    assert row is not None
    assert row.state is State.DESCRIBED
    assert len(row.evidence.image_descriptions) == 1

    enriched = await explain(runtime, OPTIONS)
    assert enriched.ok, enriched.errors
    assert enriched.done == 1
    row = await staging.load(row.id)
    assert row is not None
    assert row.state is State.ENRICHED

    reviewed = await review(runtime, OPTIONS)
    assert reviewed.ok, reviewed.errors
    assert reviewed.done == 1
    row = await staging.load(row.id)
    assert row is not None
    assert row.state is State.VERIFIED

    promoted = await ready(runtime, OPTIONS)
    assert promoted.ok, promoted.notes + promoted.errors
    assert promoted.done == 1
    row = await staging.load(row.id)
    assert row is not None
    assert row.state is State.READY


async def test_the_presets_compose_the_same_steps() -> None:
    runtime, staging, _ = make_runtime()

    scrape = await run_preset("scrape", runtime, OPTIONS)
    assert [result.task for result in scrape] == ["fetch", "tag"]
    assert all(result.ok for result in scrape), [r.errors for r in scrape]
    row = next(iter(staging.items.values()))
    assert row.state is State.CATALOGUED

    process = await run_preset("process", runtime, OPTIONS)
    assert [result.task for result in process] == ["media", "explain", "review", "ready"]
    assert all(result.ok for result in process), [r.errors for r in process]
    row = await staging.load(row.id)
    assert row is not None
    assert row.state is State.READY


async def test_fetch_resumes_without_refetching_the_figure() -> None:
    runtime, staging, fetcher = make_runtime()

    first = await fetch(runtime, OPTIONS)
    second = await fetch(runtime, OPTIONS)

    assert first.done == 1
    assert second.done == 1
    assert len(staging.items) == 1
    assert len(fetcher.urls) == 1
    assert any("resuming at deduped" in note for note in second.notes)


async def test_fetch_dry_run_writes_nothing() -> None:
    runtime, staging, fetcher = make_runtime()

    result = await fetch(runtime, TaskOptions(**{**OPTIONS.__dict__, "dry_run": True}))

    assert result.seen == 1
    assert result.done == 0
    assert staging.items == {}
    assert fetcher.urls == []


async def test_status_reports_the_pipeline_and_the_index() -> None:
    runtime, _, _ = make_runtime()
    await run_preset("scrape", runtime, OPTIONS)
    await run_preset("process", runtime, OPTIONS)

    result = await status(runtime, OPTIONS)

    assert result.ok
    assert any(note.startswith("ready") and note.strip().endswith("1") for note in result.notes)
    assert any(note.startswith("index") and "bank 1" in note for note in result.notes)


async def test_index_reloads_only_the_production_origin() -> None:
    existing = FakeIndex()
    await existing.remember(
        content_hash="bank-hash",
        near_duplicate="bank-near",
        origin="bank",
        question_id="bank-1",
    )
    production = FakeProduction(
        (
            KnownQuestion("prod-1", "prod-hash-1", "prod-near-1"),
            KnownQuestion("prod-2", "prod-hash-2", "prod-near-2"),
        )
    )
    runtime, _, _ = make_runtime(
        index=existing, production=production, source=False, media_branch=False
    )

    result = await index(runtime, OPTIONS)

    assert result.ok
    assert result.seen == 2
    assert result.done == 2
    assert await existing.count("production") == 2
    assert await existing.count("bank") == 1
