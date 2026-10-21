"""The gate service. Judge a row, move it on or refuse it."""

from datetime import UTC, datetime

from utmelab_bank.adapters.gate_service import GateService
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import (
    CatalogRef,
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
    Clearance,
    Content,
    Hashes,
    Option,
    Provenance,
    RichText,
    Scope,
    StagingItem,
)

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def make_item(**overrides: object) -> StagingItem:
    content = Content(
        stem=RichText(text="What is 2 + 2?"),
        options=(
            Option(id="a", text=RichText(text="3")),
            Option(id="b", text=RichText(text="4")),
            Option(id="c", text=RichText(text="5")),
            Option(id="d", text=RichText(text="6")),
        ),
        answer="b",
        marks=1.0,
        source_explanation=RichText(text="Two and two is four."),
    )
    data: dict[str, object] = {
        "id": "source-1:item-1",
        "provenance": Provenance(
            source="source-1",
            source_url="https://example.com/items/1",
            source_item_id="item-1",
            fetched_at=NOW,
            payload_hash="b" * 64,
            source_version="1.0.0",
            scope=Scope(exam="JAMB", subject="mathematics", year=2025),
        ),
        "content": content,
        "state": State.ADAPTED,
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return StagingItem.model_validate(data)


def placement(**overrides: object) -> CatalogRef:
    data: dict[str, object] = {
        "exam": "JAMB",
        "subject": "mathematics",
        "year": 2025,
        "topic_id": "algebra",
        "subtopic_id": "surds",
        "catalog_version": "2026.1",
    }
    data.update(overrides)
    return CatalogRef.model_validate(data)


def catalog() -> CatalogSnapshot:
    return CatalogSnapshot(
        version="2026.1",
        exam="JAMB",
        subject="mathematics",
        topics=(CatalogTopic(id="algebra", slug="algebra", name="Algebra"),),
        subtopics=(
            CatalogSubtopic(
                id="surds", slug="surds", name="Surds", topic_id="algebra"
            ),
        ),
    )


def test_a_clean_item_moves_to_gated() -> None:
    service = GateService()

    moved = service.apply(make_item())

    assert moved.state is State.GATED
    assert moved.error is None


def test_a_refused_item_keeps_the_reason() -> None:
    service = GateService()

    refused = service.apply(make_item(content=make_item().content.model_copy(
        update={"source_explanation": None}
    )))

    assert refused.state is State.REJECTED
    assert refused.error is not None
    assert "explanation_missing" in refused.error


def test_the_judgement_is_refused_until_a_person_clears_it() -> None:
    content = Content(
        stem=RichText(text="In the graph below, the slope is:"),
        options=(
            Option(id="a", text=RichText(text="one")),
            Option(id="b", text=RichText(text="two")),
            Option(id="c", text=RichText(text="three")),
            Option(id="d", text=RichText(text="four")),
        ),
        answer="a",
        marks=1.0,
        source_explanation=RichText(text="The slope is read off the graph."),
    )
    item = make_item(content=content)

    refused = GateService().apply(item)
    assert refused.state is State.REJECTED

    clearance = Clearance(
        rule="missing_figure",
        by="owner",
        reason="the word is ordinary, there is no figure to add",
        created_at=NOW,
    )
    cleared = GateService(clearances={"source-1:item-1": [clearance]}).apply(item)

    assert cleared.state is State.GATED


def test_the_known_hashes_catch_a_duplicate() -> None:
    service = GateService(known_hashes=["c" * 64])
    item = make_item(hashes=Hashes(payload_hash="b" * 64, content_hash="c" * 64, bundle_hash="d" * 64))

    refused = service.apply(item)

    assert refused.state is State.REJECTED
    assert "duplicate_content" in (refused.error or "")


def test_the_known_ids_catch_a_duplicate() -> None:
    service = GateService(known_ids=["source-1:item-1"])

    refused = service.apply(make_item())

    assert refused.state is State.REJECTED
    assert "duplicate_id" in (refused.error or "")


def test_a_run_reports_the_counts_per_rule() -> None:
    service = GateService()
    bad = make_item(
        id="source-1:item-2",
        provenance=Provenance(
            source="source-1",
            source_url="https://example.com/items/2",
            source_item_id="item-2",
            fetched_at=NOW,
            payload_hash="b" * 64,
            source_version="1.0.0",
            scope=Scope(exam="JAMB", subject="mathematics", year=2025),
        ),
        content=make_item().content.model_copy(update={"source_explanation": None}),
    )

    judged = service.apply_all([make_item(), bad])

    assert [item.state for item in judged] == [State.GATED, State.REJECTED]
    assert service.last_counts == {"explanation_missing": 1}


def test_the_placement_is_checked_against_the_catalog() -> None:
    service = GateService(catalog=catalog())

    gated = service.apply(make_item(catalog=placement()))
    assert gated.state is State.GATED

    refused = service.apply(make_item(catalog=placement(subtopic_id="not-there")))
    assert refused.state is State.REJECTED
    assert "subtopic_not_in_catalog" in (refused.error or "")


def test_the_queue_is_what_the_person_works_through() -> None:
    """Every refusal is in it, a defect and a judgement alike."""
    service = GateService()
    good = make_item()
    bad = make_item(
        id="source-1:item-2",
        provenance=Provenance(
            source="source-1",
            source_url="https://example.com/items/2",
            source_item_id="item-2",
            fetched_at=NOW,
            payload_hash="b" * 64,
            source_version="1.0.0",
            scope=Scope(exam="JAMB", subject="mathematics", year=2025),
        ),
        content=make_item().content.model_copy(update={"source_explanation": None}),
    )

    queue = service.queue([good, bad])

    assert list(queue) == ["source-1:item-2"]
    assert [issue.code for issue in queue["source-1:item-2"]] == [
        "explanation_missing"
    ]


def test_a_cleared_item_leaves_the_queue() -> None:
    clearance = Clearance(
        rule="explanation_missing",
        by="owner",
        reason="handled",
        created_at=NOW,
    )
    service = GateService(clearances={"source-1:item-1": [clearance]})
    item = make_item(
        content=make_item().content.model_copy(update={"source_explanation": None})
    )

    assert service.queue([item]) == {}
    assert service.apply(item).state is State.GATED


def test_the_judgement_does_not_change_the_item() -> None:
    """Judging is not moving. The gate reports, the state machine decides."""
    item = make_item()
    service = GateService()

    verdict = service.judge(item)

    assert verdict.passed is True
    assert item.state is State.ADAPTED
