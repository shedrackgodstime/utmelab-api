from collections.abc import AsyncIterator
from datetime import datetime, UTC

from utmelab_pipeline.domain.capabilities import (
    CAPABILITY_INPUTS,
    CAPABILITY_OUTPUTS,
    DescribeImageRequest,
    ExplainRequest,
    TagRequest,
    VerifyAnswerRequest,
)
from utmelab_pipeline.domain.enums import Capability
from utmelab_pipeline.domain.models.common import (
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
    Coverage,
    MediaAsset,
    Producer,
    Scope,
    SourceCapabilities,
    SourceItem,
    SourceProfile,
    StagingItem,
    Provenance,
    Content,
    RichText,
    Option,
)
from utmelab_pipeline.domain.ports import (
    AnswerVerifier,
    CatalogReader,
    Explainer,
    ImageDescriber,
    MediaStore,
    Source,
    StagingStore,
    Tagger,
)


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

    async def fetch(self, scope: Scope): ...

    def adapt(self, item: SourceItem, catalog) -> StagingItem:
        raise NotImplementedError

    def validate(self, item: SourceItem) -> list[str]:
        raise NotImplementedError


class FakeDescriber:
    producer = Producer(provider="example", model="vision")

    async def describe(self, request): ...


class FakeExplainer:
    producer = Producer(provider="example", model="text")

    async def explain(self, request): ...


class FakeTagger:
    producer = Producer(provider="example", model="text")

    async def tag(self, request): ...


class FakeVerifier:
    producer = Producer(provider="example", model="text")

    async def verify(self, request): ...


class FakeCatalog:
    async def snapshot(self, exam: str, subject: str): ...


class FakeMediaStore:
    async def put(self, data: bytes, *, mime: str, source_url: str | None = None): ...

    async def read(self, asset_id: str) -> bytes: ...

    async def exists(self, asset_id: str) -> bool: ...


class FakeStagingStore:
    async def save(self, item): ...

    async def load(self, item_id: str): ...

    async def transition(self, item_id: str, to_state: str, *, error: str | None = None): ...

    async def list_by_state(self, state: str, *, limit: int = 100): ...


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
    from utmelab_pipeline.domain.enums import Capability
    from utmelab_pipeline.domain.capabilities import CAPABILITY_INPUTS, CAPABILITY_OUTPUTS
    assert set(CAPABILITY_INPUTS) == set(Capability)
    assert set(CAPABILITY_OUTPUTS) == set(Capability)


def test_describe_image_request_carries_asset() -> None:
    from utmelab_pipeline.domain.capabilities import DescribeImageRequest
    from utmelab_pipeline.domain.models.common import MediaAsset
    from datetime import datetime, UTC
    asset = MediaAsset(
        asset_id="a" * 64,
        mime="image/png",
        byte_size=1234,
        width=100,
        height=50,
        storage_url="file:///tmp/figure.png",
        source_url="https://example.com/figure.png",
        fetched_at=datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
    )
    request = DescribeImageRequest(asset=asset, context="A labelled cell")
    assert request.asset.asset_id == "a" * 64


def test_tag_request_requires_catalog() -> None:
    from utmelab_pipeline.domain.capabilities import TagRequest
    from utmelab_pipeline.domain.models.common import (
        StagingItem, CatalogSnapshot, CatalogSubtopic, CatalogTopic,
        Provenance, Content, RichText, Option, Scope, Producer,
    )
    from datetime import datetime, UTC
    NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    catalog = CatalogSnapshot(
        version="2026.1",
        exam="JAMB",
        subject="Biology",
        topics=(CatalogTopic(id="t1", slug="cell", name="Cell"),),
        subtopics=(
            CatalogSubtopic(
                id="s1",
                slug="cell-structure",
                name="Cell structure",
                topic_id="t1",
            ),
        ),
    )
    prov = Provenance(
        source="test", source_url="https://example.com", source_item_id="item1",
        fetched_at=NOW, payload_hash="a" * 64, source_version="1.0",
        scope=Scope(exam="JAMB", subject="Bio", year=2024)
    )
    item = StagingItem(
            id="test",
            provenance=prov,
            content=Content(
                stem=RichText(text="test"),
                options=(
                    Option(id="A", text=RichText(text="1")),
                    Option(id="B", text=RichText(text="2")),
                ),
                answer="A",
                marks=1.0,
            ),
            state="adapted",
            created_at=datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
            updated_at=datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
        )
    catalog = CatalogSnapshot(
        version="2026.1",
        exam="JAMB",
        subject="Biology",
        topics=(CatalogTopic(id="t1", slug="cell", name="Cell"),),
        subtopics=(
            CatalogSubtopic(
                id="s1",
                slug="cell-structure",
                name="Cell structure",
                topic_id="t1",
            ),
        ),
    )
    from utmelab_pipeline.domain.capabilities import TagRequest
    request = TagRequest(item=item, catalog=catalog)
    assert request.catalog.version == "2026.1"