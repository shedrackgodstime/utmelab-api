"""Tests for the port contracts. The core depends on these shapes, not on adapters."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from utmelab_bank.domain.capabilities import (
    DescribeImageRequest,
    ExplainRequest,
    TagRequest,
    VerifyAnswerRequest,
)
from utmelab_bank.domain.enums import Capability
from utmelab_bank.domain.models import (
    CatalogSnapshot,
    Coverage,
    MediaAsset,
    Producer,
    Scope,
    SourceCapabilities,
    SourceItem,
    SourceProfile,
    StagingItem,
)
from utmelab_bank.domain.ports import (
    AnswerVerifier,
    CatalogReader,
    Explainer,
    ImageDescriber,
    MediaStore,
    Source,
    StagingStore,
    Tagger,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class FakeSource:
    profile = SourceProfile(
        name="source-1",
        version="1.0.0",
        exams=("JAMB",),
        subjects={"Biology": "Biology"},
        capabilities=SourceCapabilities(),
    )

    async def probe(self, scope: Scope) -> Coverage:
        raise NotImplementedError

    def fetch(self, scope: Scope) -> AsyncIterator[SourceItem]:
        raise NotImplementedError

    def adapt(self, item: SourceItem, catalog: CatalogSnapshot) -> StagingItem:
        raise NotImplementedError

    def validate(self, item: SourceItem) -> list[str]:
        raise NotImplementedError


class FakeDescriber:
    producer = Producer(provider="example", model="vision")

    async def describe(self, request: DescribeImageRequest) -> object:
        raise NotImplementedError


class FakeExplainer:
    producer = Producer(provider="example", model="text")

    async def explain(self, request: ExplainRequest) -> object:
        raise NotImplementedError


class FakeTagger:
    producer = Producer(provider="example", model="text")

    async def tag(self, request: TagRequest) -> object:
        raise NotImplementedError


class FakeVerifier:
    producer = Producer(provider="example", model="text")

    async def verify(self, request: VerifyAnswerRequest) -> object:
        raise NotImplementedError


class FakeCatalog:
    async def snapshot(self, exam: str, subject: str) -> CatalogSnapshot:
        raise NotImplementedError


class FakeMediaStore:
    async def put(
        self,
        data: bytes,
        *,
        mime: str,
        source_url: str | None = None,
    ) -> MediaAsset:
        raise NotImplementedError

    async def read(self, name: str) -> bytes:
        raise NotImplementedError

    async def exists(self, name: str) -> bool:
        raise NotImplementedError

    def served_url(self, name: str) -> str | None:
        raise NotImplementedError


class FakeStagingStore:
    async def save(self, item: StagingItem) -> None:
        raise NotImplementedError

    async def load(self, item_id: str) -> StagingItem | None:
        raise NotImplementedError

    async def transition(
        self,
        item_id: str,
        expected: str,
        target: str,
        *,
        error: str | None = None,
    ) -> StagingItem:
        raise NotImplementedError

    async def list_by_state(self, state: str, *, limit: int = 100) -> tuple[StagingItem, ...]:
        raise NotImplementedError


def test_ports_accept_structural_implementations() -> None:
    assert isinstance(FakeSource(), Source)
    assert isinstance(FakeDescriber(), ImageDescriber)
    assert isinstance(FakeExplainer(), Explainer)
    assert isinstance(FakeTagger(), Tagger)
    assert isinstance(FakeVerifier(), AnswerVerifier)
    assert isinstance(FakeCatalog(), CatalogReader)
    assert isinstance(FakeMediaStore(), MediaStore)
    assert isinstance(FakeStagingStore(), StagingStore)


def test_ports_reject_plain_objects() -> None:
    assert not isinstance(object(), Source)
    assert not isinstance(object(), StagingStore)


def test_capability_maps_are_complete() -> None:
    from utmelab_bank.domain.capabilities import (
        CAPABILITY_INPUTS,
        CAPABILITY_OUTPUTS,
    )

    assert set(CAPABILITY_INPUTS) == set(Capability)
    assert set(CAPABILITY_OUTPUTS) == set(Capability)


def test_describe_image_request_carries_asset() -> None:
    asset = MediaAsset(
        asset_id="a" * 64,
        mime="image/png",
        byte_size=1234,
        width=100,
        height=50,
        storage_url="file:///tmp/figure.png",
        source_url="https://example.com/figure.png",
        fetched_at=NOW,
    )
    request = DescribeImageRequest(asset=asset, context="A labelled cell")
    assert request.asset.asset_id == asset.asset_id
