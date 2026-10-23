"""The task runner, proved end to end without a network or a model."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from utmelab_bank.adapters.gate_service import GateService
from utmelab_bank.adapters.media import (
    DescribeImageConsensus,
    MediaError,
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
    Content,
    Inline,
    MediaAsset,
    Producer,
    RichText,
    StagingItem,
)
from utmelab_bank.runtime import Runtime
from utmelab_bank.tasks import (
    TaskOptions,
    _advance,
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

from .media_fakes import PNG_1X1, FakeMediaFetcher, FakeMediaStore

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

    async def states_for(
        self,
        *,
        exam: str,
        subject: str,
        year: int,
    ) -> dict[str, tuple[str, bool, bool]]:
        return {
            item.id: (
                item.state.value,
                item.error is not None,
                bool(item.media_refs) or bool(item.media_blobs),
            )
            for item in self.items.values()
            if item.provenance.scope.exam == exam
            and item.provenance.scope.subject == subject
            and item.provenance.scope.year == year
        }

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

    async def forget_question(self, question_id: str, *, origin: str = "bank") -> None:
        self.rows = [row for row in self.rows if not (row[2] == origin and row[3] == question_id)]

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
    assert [result.task for result in scrape] == ["fetch"]
    assert all(result.ok for result in scrape), [r.errors for r in scrape]
    row = next(iter(staging.items.values()))
    # fetch now captures figures inline, so the row is DEDUPED with media_assets
    assert row.state is State.DEDUPED
    assert row.media_refs == ()
    assert row.media_assets

    process = await run_preset("process", runtime, OPTIONS)
    assert [result.task for result in process] == [
        "capture",
        "tag",
        "media",
        "explain",
        "review",
        "ready",
    ]
    assert all(result.ok for result in process), [r.errors for r in process]
    row = await staging.load(row.id)
    assert row is not None
    assert row.state is State.READY



async def test_fetch_resumes_without_touching_the_figure() -> None:
    runtime, staging, fetcher = make_runtime()

    first = await fetch(runtime, OPTIONS)
    second = await fetch(runtime, OPTIONS)

    assert first.done == 1
    assert second.done == 1
    assert len(staging.items) == 1
    # The first fetch captures the figure. The second sees a finished row in
    # one scope query and does not load, capture, or index it again.
    assert len(fetcher.urls) == 1
    assert not any("resuming at deduped" in note for note in second.notes)


async def test_capture_clears_blobs_after_upload(staging_item: StagingItem) -> None:
    item = staging_item.model_copy(
        update={
            "id": "blob-item",
            "state": State.DEDUPED,
            "content": Content(
                stem=RichText(
                    text="The diagram shows a cell.",
                    inline=(
                        Inline(
                            kind="image",
                            start=0,
                            len=0,
                            url="blob:figure",
                            position="below",
                        ),
                    ),
                ),
                options=staging_item.content.options,
                answer=staging_item.content.answer,
                marks=staging_item.content.marks,
            ),
            "media_refs": (),
            "media_assets": (),
            "media_blobs": {"figure": PNG_1X1},
        }
    )
    ingestor = MediaIngestor(FakeMediaFetcher(), PillowMediaValidator(), FakeMediaStore())

    captured = await ingestor.capture_refs(item)

    assert captured.media_blobs == {}
    assert len(captured.media_assets) == 1
    assert captured.content.stem.inline[0].url == captured.media_assets[0].storage_url


class ExplodingIngestor:
    """Capture must not run twice for a row that already owns its figures."""

    async def capture_refs(self, item: StagingItem) -> StagingItem:
        raise AssertionError(f"capture ran again for {item.id}")


async def test_advance_drops_stale_blobs_without_recapturing(
    staging_item: StagingItem,
    media: MediaAsset,
) -> None:
    runtime, staging, _ = make_runtime()
    item = staging_item.model_copy(
        update={
            "id": "stale-blob",
            "state": State.DEDUPED,
            "media_refs": (),
            "media_assets": (media,),
            "media_blobs": {"figure": PNG_1X1},
        }
    )
    await staging.save(item)

    advanced = await _advance(
        runtime,
        item,
        GateService(catalog=None, known_passage_ids=frozenset()),
        ExplodingIngestor(),  # type: ignore[arg-type]
    )

    assert advanced.media_blobs == {}
    assert advanced.media_assets == (media,)


def _blob_item(staging_item: StagingItem, *, key: str = "figure") -> StagingItem:
    return staging_item.model_copy(
        update={
            "id": f"blob-{key}",
            "state": State.DEDUPED,
            "content": Content(
                stem=RichText(
                    text="The diagram shows a cell.",
                    inline=(
                        Inline(
                            kind="image",
                            start=0,
                            len=0,
                            url=f"blob:{key}",
                            position="below",
                        ),
                    ),
                ),
                options=staging_item.content.options,
                answer=staging_item.content.answer,
                marks=staging_item.content.marks,
            ),
            "media_refs": (),
            "media_assets": (),
            "media_blobs": {},
        }
    )


async def test_capture_rejects_an_inline_figure_the_bank_cannot_serve(
    staging_item: StagingItem,
) -> None:
    item = _blob_item(staging_item).model_copy(update={"media_blobs": {"figure": PNG_1X1}})
    ingestor = MediaIngestor(
        FakeMediaFetcher(),
        PillowMediaValidator(),
        FakeMediaStore(published=False),
    )

    with pytest.raises(MediaError, match="cannot be served"):
        await ingestor.capture_refs(item)


async def test_capture_rejects_an_inline_figure_with_no_bytes(
    staging_item: StagingItem,
) -> None:
    ingestor = MediaIngestor(FakeMediaFetcher(), PillowMediaValidator(), FakeMediaStore())

    with pytest.raises(MediaError, match="no captured bytes"):
        await ingestor.capture_refs(_blob_item(staging_item))


async def test_advance_clears_an_old_error_after_a_successful_resume(
    staging_item: StagingItem,
    media: MediaAsset,
) -> None:
    runtime, staging, _ = make_runtime()
    item = staging_item.model_copy(
        update={
            "id": "retried-row",
            "state": State.DEDUPED,
            "media_refs": (),
            "media_assets": (media,),
            "media_blobs": {},
            "error": "MediaError: the host is gone",
        }
    )
    await staging.save(item)

    advanced = await _advance(
        runtime,
        item,
        GateService(catalog=None, known_passage_ids=frozenset()),
        ExplodingIngestor(),  # type: ignore[arg-type]
    )

    assert advanced.error is None
    assert advanced.state is State.DEDUPED


async def test_fetch_dry_run_writes_nothing() -> None:
    runtime, staging, fetcher = make_runtime()

    result = await fetch(runtime, TaskOptions(**{**OPTIONS.__dict__, "dry_run": True}))

    assert result.seen == 1
    assert result.done == 0
    assert staging.items == {}
    assert fetcher.urls == []


async def test_a_duplicate_is_filtered_without_uploading_a_figure() -> None:
    runtime, staging, fetcher = make_runtime()
    source = runtime.source
    assert source is not None
    raw = [item async for item in source.fetch(OPTIONS)][0]
    adapted = source.adapt(raw, make_catalog())
    dedupe = runtime.dedupe
    await runtime.index.remember(
        content_hash=dedupe.content_key(adapted),
        near_duplicate=dedupe.near_key(adapted),
        origin="production",
        question_id="production:1",
    )

    result = await fetch(runtime, OPTIONS)

    assert result.ok
    assert result.done == 0
    assert result.skipped == 1
    row = next(iter(staging.items.values()))
    assert row.state is State.REJECTED
    assert "duplicate_exact" in (row.error or "")
    assert row.media_assets == ()
    assert fetcher.urls == []


async def test_a_capture_that_changes_the_hash_is_rechecked() -> None:
    runtime, _, _ = make_runtime()
    source = runtime.source
    assert source is not None
    raw = [item async for item in source.fetch(OPTIONS)][0]
    adapted = source.adapt(raw, make_catalog())

    ingestor = runtime.ingestor
    assert ingestor is not None
    captured = await ingestor.capture_refs(adapted)
    dedupe = runtime.dedupe
    await runtime.index.remember(
        content_hash=dedupe.content_key(captured),
        near_duplicate=dedupe.near_key(captured),
        origin="production",
        question_id="production:figure",
    )

    advanced = await _advance(
        runtime,
        adapted.transition_to(State.GATED),
        GateService(catalog=make_catalog(), known_passage_ids=frozenset()),
        ingestor,
    )

    assert advanced.state is State.REJECTED
    assert "duplicate_exact" in (advanced.error or "")


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
