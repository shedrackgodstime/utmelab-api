import asyncio
from pathlib import Path

import pytest

from utmelab_pipeline.adapters.sources.fixture import FixtureSource
from utmelab_pipeline.domain.enums import SourceCapability
from utmelab_pipeline.domain.models import (
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
    Scope,
    SourceItem,
)
from utmelab_pipeline.domain.ports import Source

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sources" / "fixture"
SCOPE = Scope(exam="JAMB", subject="Biology", year=2024, section="A")


def make_catalog() -> CatalogSnapshot:
    return CatalogSnapshot(
        version="2026.1",
        exam="JAMB",
        subject="Biology",
        topics=(
            CatalogTopic(id="cell-biology", slug="cell-biology", name="Cell biology"),
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


def collect(source: Source, scope: Scope) -> list[SourceItem]:
    async def run() -> list[SourceItem]:
        return [item async for item in source.fetch(scope)]

    return asyncio.run(run())


def test_fixture_source_matches_the_port() -> None:
    source: Source = FixtureSource(FIXTURE_DIR)
    assert isinstance(source, Source)
    assert source.profile.capabilities.supports(SourceCapability.FIGURES)
    assert source.profile.capabilities.supports(SourceCapability.MARKS)


def test_probe_counts_recorded_items() -> None:
    source = FixtureSource(FIXTURE_DIR)
    coverage = asyncio.run(source.probe(SCOPE))
    assert coverage.item_count == 1
    assert coverage.has_more is False


def test_probe_unknown_scope_is_empty() -> None:
    source = FixtureSource(FIXTURE_DIR)
    coverage = asyncio.run(
        source.probe(Scope(exam="JAMB", subject="Biology", year=2030))
    )
    assert coverage.item_count == 0


def test_fetch_returns_provenance() -> None:
    source = FixtureSource(FIXTURE_DIR)
    items = collect(source, SCOPE)
    assert len(items) == 1
    item = items[0]
    assert item.external_key == "fixture:bio-2024-001"
    assert item.scope == SCOPE
    assert len(item.payload_hash) == 64


def test_valid_item_has_no_issues() -> None:
    source = FixtureSource(FIXTURE_DIR)
    item = collect(source, SCOPE)[0]
    assert source.validate(item) == []


def test_adapt_builds_a_raw_bundle() -> None:
    source = FixtureSource(FIXTURE_DIR)
    item = collect(source, SCOPE)[0]
    raw = source.adapt(item, make_catalog())

    assert raw.id == "fixture:bio-2024-001"
    assert raw.content.answer == "A"
    assert raw.content.stem.marks[0].asset_id == "cell-diagram"
    assert raw.media_refs[0].key == "cell-diagram"
    assert raw.media_refs[0].required is True
    assert raw.catalog.catalog_version == "2026.1"
    assert raw.catalog.subtopic_id == "cell-structure"


def test_adapt_rejects_an_unknown_catalog_entry() -> None:
    source = FixtureSource(FIXTURE_DIR)
    item = collect(source, SCOPE)[0]
    other_catalog = CatalogSnapshot(
        version="2026.1",
        exam="JAMB",
        subject="Biology",
        topics=(CatalogTopic(id="other", slug="other", name="Other"),),
        subtopics=(
            CatalogSubtopic(
                id="other-sub",
                slug="other-sub",
                name="Other sub",
                topic_id="other",
            ),
        ),
    )
    with pytest.raises(ValueError, match="catalog"):
        source.adapt(item, other_catalog)


def test_invalid_record_reports_issues() -> None:
    source = FixtureSource(FIXTURE_DIR)
    item = collect(source, Scope(exam="JAMB", subject="Biology", year=2025))[0]
    codes = set(source.validate(item))
    assert any("source.answer" in c for c in codes)
    assert any("source.mark" in c for c in codes)


def test_payload_hash_is_stable_across_fetches() -> None:
    source = FixtureSource(FIXTURE_DIR)
    first = collect(source, SCOPE)[0]
    second = collect(source, SCOPE)[0]
    assert first.payload_hash == second.payload_hash
