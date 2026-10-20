from datetime import UTC, datetime
from typing import TypeVar

import pytest
from pydantic import BaseModel

from utmelab_pipeline.domain.enums import MarkKind, State
from utmelab_pipeline.domain.models import (
    StagingItem,
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
    Content,
    Evidence,
    Hashes,
    MediaAsset,
    Mark,
    Option,
    Provenance,
    RichText,
    Scope,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
MEDIA_ID = "a" * 64
PAYLOAD_HASH = "b" * 64
CONTENT_HASH = "c" * 64
BUNDLE_HASH = "d" * 64

M = TypeVar("M", bound=BaseModel)


def rebuild(model: M, **updates: object) -> M:
    data = model.model_dump(mode="json")
    data.update(updates)
    return type(model).model_validate(data)


@pytest.fixture
def content() -> Content:
    return Content(
        stem=RichText(text="What is 2 + 2?"),
        options=(
            Option(id="A", text=RichText(text="3")),
            Option(id="B", text=RichText(text="4")),
            Option(id="C", text=RichText(text="5")),
            Option(id="D", text=RichText(text="6")),
        ),
        answer="B",
        marks=1.0,
    )


@pytest.fixture
def provenance() -> Provenance:
    return Provenance(
        source="source-1",
        source_url="https://example.com/items/1",
        source_item_id="item-1",
        fetched_at=NOW,
        payload_hash=PAYLOAD_HASH,
        source_version="1.0.0",
        scope=Scope(exam="JAMB", subject="Biology", year=2024),
    )


@pytest.fixture
def media() -> MediaAsset:
    return MediaAsset(
        asset_id=MEDIA_ID,
        mime="image/png",
        byte_size=1234,
        width=100,
        height=50,
        storage_url="file:///tmp/figure.png",
        source_url="https://example.com/figure.png",
        fetched_at=NOW,
    )


@pytest.fixture
def catalog() -> CatalogSnapshot:
    return CatalogSnapshot(
        version="2026.1",
        exam="JAMB",
        subject="Biology",
        topics=(
            CatalogTopic(id="t1", slug="cell", name="Cell"),
            CatalogTopic(id="t2", slug="genetics", name="Genetics"),
        ),
        subtopics=(
            CatalogSubtopic(
                id="s1",
                slug="cell-structure",
                name="Cell structure",
                topic_id="t1",
            ),
            CatalogSubtopic(
                id="s2",
                slug="inheritance",
                name="Inheritance",
                topic_id="t2",
            ),
        ),
    )


@pytest.fixture
def staging_item(content: Content, provenance: Provenance) -> StagingItem:
    return StagingItem(
        id=provenance.external_key,
        provenance=provenance,
        content=content,
        media_refs=(),
        media_assets=(),
        evidence=Evidence(),
        catalog=None,
        state=State.CATALOGUED.value,
        hashes=Hashes(payload_hash=PAYLOAD_HASH, content_hash=CONTENT_HASH, bundle_hash=BUNDLE_HASH),
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def image_content() -> Content:
    return Content(
        stem=RichText(
            text="The diagram shows a cell.",
            marks=(Mark(kind="image", start=0, length=0, asset_id="e" * 64),),
        ),
        options=(
            Option(id="A", text=RichText(text="Nucleus")),
            Option(id="B", text=RichText(text="Cytoplasm")),
            Option(id="C", text=RichText(text="Membrane")),
            Option(id="D", text=RichText(text="Wall")),
        ),
        answer="A",
        marks=1.0,
    )

__all__ = [
    "BUNDLE_HASH",
    "CONTENT_HASH",
    "MEDIA_ID",
    "NOW",
    "PAYLOAD_HASH",
    "rebuild",
]
