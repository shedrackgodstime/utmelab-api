import pytest
from pydantic import ValidationError

from utmelab_pipeline.domain.enums import State
from utmelab_pipeline.domain.models import (
    StagingItem,
    Content,
    Evidence,
    MediaAsset,
)
from utmelab_pipeline.domain.selector import Selector

from .conftest import rebuild


def test_default_selector_matches_state(staging_item: StagingItem) -> None:
    assert Selector(state=State.CATALOGUED).matches(staging_item)


def test_selector_matches_full_scope(staging_item: StagingItem) -> None:
    selector = Selector(
        state=State.CATALOGUED,
        source="source-1",
        exam="JAMB",
        subject="Biology",
        year=2024,
        has_media=False,
    )
    assert selector.matches(staging_item)


def test_selector_rejects_wrong_state(staging_item: StagingItem) -> None:
    assert not Selector(state=State.ACQUIRED).matches(staging_item)


def test_selector_rejects_wrong_scope(staging_item: StagingItem) -> None:
    assert not Selector(state=State.CATALOGUED, source="source-2").matches(staging_item)
    assert not Selector(state=State.CATALOGUED, exam="WAEC").matches(staging_item)
    assert not Selector(state=State.CATALOGUED, subject="Chemistry").matches(staging_item)
    assert not Selector(state=State.CATALOGUED, year=2023).matches(staging_item)


def test_selector_filters_on_media(staging_item: StagingItem) -> None:
    assert Selector(state=State.CATALOGUED, has_media=False).matches(staging_item)
    assert not Selector(state=State.CATALOGUED, has_media=True).matches(staging_item)


def test_selector_matches_bundle_with_media(
    staging_item: StagingItem, image_content: Content, media: MediaAsset
) -> None:
    asset = rebuild(media, asset_id="e" * 64)
    with_media = StagingItem(
        id=staging_item.id,
        provenance=staging_item.provenance,
        content=image_content,
        media_refs=(),
        media_assets=(asset,),
        evidence=Evidence(),
        state=staging_item.state,
        hashes=staging_item.hashes,
        created_at=staging_item.created_at,
        updated_at=staging_item.updated_at,
    )
    assert Selector(state=State.CATALOGUED, has_media=True).matches(with_media)
    assert not Selector(state=State.CATALOGUED, has_media=False).matches(with_media)


def test_selector_limit_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Selector(state=State.CATALOGUED, limit=0)
    with pytest.raises(ValidationError):
        Selector(state=State.CATALOGUED, limit=1001)