"""The media branch: capture, store, swap the url, describe."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from tests.fakes.mock_provider import MockProvider
from tests.media_fakes import FailingMediaFetcher, FakeMediaFetcher, FakeMediaStore
from utmelab_bank.adapters.media import (
    DescribeImageConsensus,
    MediaIngestor,
    MediaService,
    PillowMediaValidator,
)
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.hashing import bundle_fingerprint
from utmelab_bank.domain.models import (
    Content,
    DescribeImageRequest,
    ImageDescription,
    Inline,
    MediaRef,
    OcrRecord,
    Option,
    Producer,
    Provenance,
    RichText,
    Scope,
    StagingItem,
)
from utmelab_bank.domain.ports import MediaFetcher

SOURCE_URL = "https://source.example/figure.png"
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def make_item(*, required: bool = False, with_media: bool = True) -> StagingItem:
    inline = (
        (Inline(kind="image", start=0, len=0, url=SOURCE_URL, position="below"),)
        if with_media
        else ()
    )
    content = Content(
        stem=RichText(text="The diagram shows a cell.", inline=inline),
        options=(
            Option(id="a", text=RichText(text="nucleus")),
            Option(id="b", text=RichText(text="membrane")),
            Option(id="c", text=RichText(text="wall")),
            Option(id="d", text=RichText(text="vacuole")),
        ),
        answer="a",
        marks=1.0,
    )
    provenance = Provenance(
        source="fixture",
        source_url="https://source.example/items/1",
        source_item_id="fig-1",
        fetched_at=NOW,
        payload_hash="b" * 64,
        source_version="1.0.0",
        scope=Scope(exam="JAMB", subject="Biology", year=2024, section="A"),
    )
    refs = (MediaRef(key="fig1", source_url=SOURCE_URL, required=required),) if with_media else ()
    return StagingItem(
        id=provenance.external_key,
        provenance=provenance,
        content=content,
        media_refs=refs,
        state=State.CATALOGUED,
        created_at=NOW,
        updated_at=NOW,
    ).stamp_hashes()


def ingestor(store: FakeMediaStore, fetcher: MediaFetcher | None = None) -> MediaIngestor:
    return MediaIngestor(fetcher or FakeMediaFetcher(), PillowMediaValidator(), store)


def test_capture_records_the_name_and_leaves_the_state_alone() -> None:
    """The capture step stores without moving the row or keeping the refs."""
    store = FakeMediaStore()
    result = asyncio.run(ingestor(store).capture_refs(make_item()))

    assert result.state is State.CATALOGUED
    assert result.media_refs == ()
    assert len(result.media_assets) == 1
    asset = result.media_assets[0]
    assert asset.storage_url == f"{asset.asset_id}.png"


def test_ingesting_owns_the_asset_and_swaps_the_url() -> None:
    item = make_item()
    before = item.hashes
    store = FakeMediaStore()

    result = asyncio.run(ingestor(store).ingest_refs(item))

    assert result.state is State.MEDIA_READY
    assert len(result.media_assets) == 1
    asset = result.media_assets[0]

    # The bank owns it: the source url is gone and the inline records the name.
    assert asset.source_url is None
    assert not asset.storage_url.startswith("https://")
    assert result.content.stem.inline[0].url == asset.storage_url

    # Swapping a url changes the content fingerprint, and attaching an asset
    # changes the bundle fingerprint, so both are re-stamped.
    assert result.hashes is not None
    assert before is not None
    assert result.hashes.content_hash != before.content_hash
    assert result.hashes.bundle_hash != before.bundle_hash
    assert result.hashes.bundle_hash == bundle_fingerprint(
        content_hash=result.hashes.content_hash,
        section="A",
        media_ids=(asset.asset_id,),
    )


def test_a_store_that_cannot_serve_keeps_the_source_url() -> None:
    result = asyncio.run(ingestor(FakeMediaStore(published=False)).ingest_refs(make_item()))

    assert result.state is State.MEDIA_READY
    asset = result.media_assets[0]
    assert str(asset.source_url) == SOURCE_URL
    assert result.content.stem.inline[0].url == SOURCE_URL


def test_an_optional_ref_that_fails_is_skipped() -> None:
    result = asyncio.run(
        ingestor(FakeMediaStore(), FailingMediaFetcher()).ingest_refs(make_item(required=False))
    )

    assert result.state is State.MEDIA_READY
    assert result.media_assets == ()
    assert result.content.stem.inline[0].url == SOURCE_URL


def test_a_required_ref_that_fails_fails_the_row() -> None:
    with pytest.raises(OSError):
        asyncio.run(
            ingestor(FakeMediaStore(), FailingMediaFetcher()).ingest_refs(make_item(required=True))
        )


def test_the_media_branch_describes_the_asset() -> None:
    second = MockProvider(producer=Producer(provider="mock", model="mock-v2"))
    service = MediaService(
        ingestor(FakeMediaStore()),
        DescribeImageConsensus((MockProvider(), second)),
    )

    result = asyncio.run(service.apply(make_item(), capture=True))

    assert result.state is State.DESCRIBED
    assert len(result.evidence.image_descriptions) == 1
    assert result.evidence.image_descriptions[0].asset_id == result.media_assets[0].asset_id


def test_ocr_is_saved_and_passed_to_the_describer() -> None:
    class FakeOcr:
        producer = Producer(provider="ocr.space", model="engine-2")

        async def extract(self, *, asset_id: str, data: bytes, mime: str) -> OcrRecord:
            assert data
            assert mime == "image/png"
            return OcrRecord(
                asset_id=asset_id,
                producer=self.producer,
                text="label from figure",
            )

    class CapturingDescriber:
        producer = Producer(provider="test", model="vision")

        def __init__(self) -> None:
            self.requests: list[DescribeImageRequest] = []

        async def describe(self, request: DescribeImageRequest) -> ImageDescription:
            self.requests.append(request)
            return ImageDescription(
                asset_id=request.asset.asset_id,
                description="a figure",
                facts=(),
                confidence=0.5,
                producer=self.producer,
            )

    describer = CapturingDescriber()
    service = MediaService(
        ingestor(FakeMediaStore()),
        describer,
        ocr=FakeOcr(),
    )

    result = asyncio.run(service.apply(make_item(), capture=True))

    assert result.evidence.ocr[0].text == "label from figure"
    assert describer.requests[0].context == "OCR text extracted from this image:\nlabel from figure"


def test_a_row_that_crashed_at_media_ready_is_resumed() -> None:
    second = MockProvider(producer=Producer(provider="mock", model="mock-v2"))
    service = MediaService(
        ingestor(FakeMediaStore()),
        DescribeImageConsensus((MockProvider(), second)),
    )
    captured = asyncio.run(service.apply(make_item(), capture=True))
    # Reconstruct the state a crash between the save and the description
    # would leave behind: the bytes and the state, no description.
    crashed = captured.model_copy(
        update={"state": State.MEDIA_READY, "evidence": make_item().evidence}
    )

    result = asyncio.run(service.apply(crashed))

    assert result.state is State.DESCRIBED
    assert len(result.evidence.image_descriptions) == 1


def test_a_row_with_no_media_skips_the_branch() -> None:
    item = make_item(with_media=False)
    second = MockProvider(producer=Producer(provider="mock", model="mock-v2"))
    service = MediaService(
        ingestor(FakeMediaStore()),
        DescribeImageConsensus((MockProvider(), second)),
    )

    result = asyncio.run(service.apply(item))

    assert result is item
    assert result.state is State.CATALOGUED
