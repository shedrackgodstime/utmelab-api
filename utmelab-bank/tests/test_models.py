"""Unit tests for the canonical models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from utmelab_pipeline.domain.enums import (
    ImagePosition,
    MarkKind,
    Severity,
    SourceCapability,
    VerificationKind,
    Verdict,
)
from utmelab_pipeline.domain.models import (
    BUNDLE_HASH,
    CONTENT_HASH,
    PAYLOAD_HASH,
    CatalogRef,
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
    Content,
    Evidence,
    GateVerdict,
    Hashes,
    ImageDescription,
    Issue,
    Mark,
    MediaAsset,
    Option,
    Producer,
    RichText,
    Scope,
    SourceCapabilities,
    SourceItem,
    SourceProfile,
    StagingItem,
    Verification,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
PRODUCER = Producer(provider="example", model="example-model")


def test_valid_staging_item_keeps_facts(staging_item: StagingItem) -> None:
    assert staging_item.id == "source-1:item-1"
    assert staging_item.content.answer == "B"
    assert staging_item.content.options[1].text.text == "4"
    assert staging_item.hashes is not None
    assert staging_item.state.value == "catalogued"


def test_staging_item_id_must_match_provenance(staging_item: StagingItem) -> None:
    payload = staging_item.model_dump(mode="json")
    payload["id"] = "source-1:other"
    with pytest.raises(ValidationError, match="id"):
        StagingItem.model_validate(payload)


def test_staging_item_accepts_a_marked_figure(
    staging_item: StagingItem, image_content: Content
) -> None:
    """An image mark carries a url and a position, the production shape."""
    result = StagingItem(
        id=staging_item.id,
        provenance=staging_item.provenance,
        content=image_content,
        media_refs=(),
        media_assets=(),
        evidence=Evidence(),
        state=staging_item.state,
        hashes=staging_item.hashes,
        created_at=NOW,
        updated_at=NOW,
    )
    mark = result.content.stem.marks[0]
    assert mark.kind is MarkKind.IMAGE
    assert mark.url is not None
    assert mark.position is ImagePosition.BELOW


def test_staging_item_accepts_media_reference(
    staging_item: StagingItem, image_content: Content, media: MediaAsset
) -> None:
    asset = media.model_copy(update={"asset_id": "e" * 64})
    result = StagingItem(
        id=staging_item.id,
        provenance=staging_item.provenance,
        content=image_content,
        media_refs=(),
        media_assets=(asset,),
        evidence=Evidence(),
        state=staging_item.state,
        hashes=staging_item.hashes,
        created_at=NOW,
        updated_at=NOW,
    )
    assert result.media_assets[0].asset_id == "e" * 64


def test_staging_item_rejects_description_without_media(
    staging_item: StagingItem,
) -> None:
    description = ImageDescription(
        asset_id="f" * 64,
        description="A labelled cell diagram",
        confidence=1.0,
        producer=PRODUCER,
    )
    with pytest.raises(ValidationError, match="description references unknown media"):
        StagingItem(
            id=staging_item.id,
            provenance=staging_item.provenance,
            content=staging_item.content,
            media_refs=(),
            media_assets=(),
            evidence=Evidence(image_descriptions=(description,)),
            state=staging_item.state,
            hashes=staging_item.hashes,
            created_at=NOW,
            updated_at=NOW,
        )


def test_staging_item_accepts_catalog_matching_scope(
    staging_item: StagingItem,
) -> None:
    catalog = CatalogRef(
        exam="JAMB",
        subject="Biology",
        year=2024,
        topic_id="t1",
        subtopic_id="s1",
        catalog_version="2026.1",
    )
    result = StagingItem(
        id=staging_item.id,
        provenance=staging_item.provenance,
        content=staging_item.content,
        media_refs=(),
        media_assets=(),
        evidence=Evidence(),
        catalog=catalog,
        state=staging_item.state,
        hashes=staging_item.hashes,
        created_at=NOW,
        updated_at=NOW,
    )
    assert result.catalog == catalog


def test_staging_item_rejects_catalog_outside_scope(
    staging_item: StagingItem,
) -> None:
    catalog = CatalogRef(
        exam="JAMB",
        subject="Biology",
        year=2023,
        topic_id="t1",
        subtopic_id="s1",
        catalog_version="2026.1",
    )
    with pytest.raises(ValidationError, match="scope"):
        StagingItem(
            id=staging_item.id,
            provenance=staging_item.provenance,
            content=staging_item.content,
            media_refs=(),
            media_assets=(),
            evidence=Evidence(),
            catalog=catalog,
            state=staging_item.state,
            hashes=staging_item.hashes,
            created_at=NOW,
            updated_at=NOW,
        )


def test_content_rejects_unknown_answer() -> None:
    with pytest.raises(ValidationError, match="answer"):
        Content(
            stem=RichText(text="Pick one"),
            options=(
                Option(id="A", text=RichText(text="one")),
                Option(id="B", text=RichText(text="two")),
            ),
            answer="C",
            marks=1.0,
        )


def test_content_rejects_duplicate_option_ids() -> None:
    with pytest.raises(ValidationError, match="option ids"):
        Content(
            stem=RichText(text="Pick one"),
            options=(
                Option(id="A", text=RichText(text="one")),
                Option(id="A", text=RichText(text="two")),
            ),
            answer="A",
            marks=1.0,
        )


def test_rich_text_rejects_overlap() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        RichText(
            text="abcdef",
            marks=(
                Mark(kind=MarkKind.BOLD, start=0, len=4),
                Mark(kind=MarkKind.ITALIC, start=2, len=2),
            ),
        )


def test_rich_text_rejects_out_of_bounds() -> None:
    with pytest.raises(ValidationError, match="past the end"):
        RichText(
            text="abc",
            marks=(Mark(kind=MarkKind.BOLD, start=2, len=5),),
        )


def test_image_mark_requires_a_url() -> None:
    with pytest.raises(ValidationError, match="url"):
        Mark(kind=MarkKind.IMAGE, start=0, len=0, position=ImagePosition.BELOW)


def test_image_mark_requires_a_position() -> None:
    with pytest.raises(ValidationError, match="position"):
        Mark(
            kind=MarkKind.IMAGE,
            start=0,
            len=0,
            url="https://example.com/figure.png",
        )


def test_image_mark_rejects_nonzero_length() -> None:
    with pytest.raises(ValidationError, match="zero length"):
        Mark(
            kind=MarkKind.IMAGE,
            start=0,
            len=1,
            url="https://example.com/figure.png",
            position=ImagePosition.BELOW,
        )


def test_text_mark_rejects_a_url() -> None:
    with pytest.raises(ValidationError, match="only image marks"):
        Mark(
            kind=MarkKind.BOLD,
            start=0,
            len=1,
            url="https://example.com/figure.png",
        )


def test_gate_verdict_rejects_passed_with_error() -> None:
    issue = Issue(
        code="gate.answer", message="answer is missing", severity=Severity.ERROR
    )
    with pytest.raises(ValidationError, match="passed"):
        GateVerdict(passed=True, issues=(issue,))


def test_gate_verdict_accepts_failed_with_error() -> None:
    issue = Issue(
        code="gate.answer", message="answer is missing", severity=Severity.ERROR
    )
    verdict = GateVerdict(passed=False, issues=(issue,))
    assert verdict.issues[0].code == "gate.answer"


def test_catalog_snapshot_rejects_unknown_topic() -> None:
    with pytest.raises(ValidationError, match="unknown topic"):
        CatalogSnapshot(
            version="2026.1",
            exam="JAMB",
            subject="Biology",
            topics=(CatalogTopic(id="t1", slug="cell", name="Cell"),),
            subtopics=(
                CatalogSubtopic(
                    id="s1",
                    slug="cell-structure",
                    name="Cell structure",
                    topic_id="t2",
                ),
            ),
        )


def test_catalog_snapshot_rejects_duplicate_topic_ids() -> None:
    with pytest.raises(ValidationError, match="topic ids"):
        CatalogSnapshot(
            version="2026.1",
            exam="JAMB",
            subject="Biology",
            topics=(
                CatalogTopic(id="t1", slug="cell", name="Cell"),
                CatalogTopic(id="t1", slug="genetics", name="Genetics"),
            ),
            subtopics=(
                CatalogSubtopic(
                    id="s1",
                    slug="cell-structure",
                    name="Cell structure",
                    topic_id="t1",
                ),
            ),
        )


def test_models_are_frozen(staging_item: StagingItem) -> None:
    with pytest.raises(ValidationError):
        staging_item.content.answer = "A"  # type: ignore[misc]


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        RichText.model_validate({"text": "hello", "colour": "red"})


def test_media_asset_id_must_be_a_sha256() -> None:
    with pytest.raises(ValidationError):
        MediaAsset(
            asset_id="not-a-hash",
            mime="image/png",
            byte_size=10,
            storage_url="file:///tmp/x.png",
            fetched_at=NOW,
        )


def test_source_profile_reports_capabilities() -> None:
    profile = SourceProfile(
        name="source-1",
        version="1.0.0",
        exams=("JAMB",),
        subjects={"Biology": "Biology"},
        years=(2010, 2025),
        capabilities=SourceCapabilities(passages=True, answer=True),
    )
    assert profile.capabilities.supports(SourceCapability.PASSAGES)
    assert not profile.capabilities.supports(SourceCapability.FIGURES)


def test_source_profile_rejects_unsorted_years() -> None:
    with pytest.raises(ValidationError, match="years"):
        SourceProfile(
            name="source-1",
            version="1.0.0",
            exams=("JAMB",),
            subjects={"Biology": "Biology"},
            years=(2025, 2010),
            capabilities=SourceCapabilities(),
        )


def test_source_item_external_key() -> None:
    item = SourceItem(
        source="source-1",
        source_url="https://example.com/items/1",
        source_item_id="item-1",
        fetched_at=NOW,
        payload={"stem": "What is 2 + 2?"},
        payload_hash=PAYLOAD_HASH,
        scope=Scope(exam="JAMB", subject="Biology", year=2024),
        source_version="1.0.0",
    )
    assert item.external_key == "source-1:item-1"


def test_verification_ai_requires_producer() -> None:
    with pytest.raises(ValidationError, match="producer"):
        Verification(
            id="v-1",
            kind=VerificationKind.AI,
            verdict=Verdict.PASS,
            scope=("answer",),
            content_hash=CONTENT_HASH,
            reviewer="ai-1",
            created_at=NOW,
        )


def test_human_verification_rejects_producer() -> None:
    with pytest.raises(ValidationError, match="human"):
        Verification(
            id="v-1",
            kind=VerificationKind.HUMAN,
            verdict=Verdict.PASS,
            scope=("answer",),
            content_hash=CONTENT_HASH,
            reviewer="human-1",
            created_at=NOW,
            producer=PRODUCER,
        )


def test_hashes_are_required_fields() -> None:
    hashes = Hashes(
        payload_hash=PAYLOAD_HASH,
        content_hash=CONTENT_HASH,
        bundle_hash=BUNDLE_HASH,
    )
    assert hashes.content_hash == CONTENT_HASH
