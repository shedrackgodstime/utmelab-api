"""Contract tests for the ready bundle.

Ready is the bank's output, so the conditions it checks are the ones that
decide whether a bundle can be placed without further judgement.
"""

from datetime import UTC, datetime

from utmelab_bank.adapters.ready_service import ReadyService
from utmelab_bank.domain.enums import (
    ImagePosition,
    InlineKind,
    Severity,
    State,
    Verdict,
    VerificationKind,
)
from utmelab_bank.domain.models import (
    CatalogRef,
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
    Content,
    Evidence,
    Explanation,
    GateVerdict,
    Hashes,
    Inline,
    Issue,
    Option,
    Producer,
    Provenance,
    RichText,
    Scope,
    StagingItem,
    Verification,
)
from utmelab_bank.domain.ready import ReadyCondition

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
PRODUCER = Producer(provider="opencode", model="nemotron-3-ultra")


def catalog() -> CatalogSnapshot:
    return CatalogSnapshot(
        version="2026.1",
        exam="JAMB",
        subject="mathematics",
        topics=(CatalogTopic(id="algebra", slug="algebra", name="Algebra"),),
        subtopics=(CatalogSubtopic(id="surds", slug="surds", name="Surds", topic_id="algebra"),),
    )


def make_item(
    *,
    item_id: str = "live:q1",
    state: State = State.VERIFIED,
    gated: bool = True,
    reviewed: bool = True,
    placed: bool = True,
    explained: bool = True,
    hashed: bool = True,
    with_hash: bool = True,
    stem_marks: tuple[Inline, ...] = (),
) -> StagingItem:
    provenance = Provenance(
        source="live",
        source_url="https://example.com/q1",
        source_item_id=item_id.split(":")[-1],
        fetched_at=NOW,
        payload_hash="b" * 64,
        source_version="1",
        scope=Scope(exam="JAMB", subject="mathematics", year=2025),
    )
    content = Content(
        stem=RichText(text="What is 2 + 2?", inline=stem_marks),
        options=(
            Option(id="a", text=RichText(text="3")),
            Option(id="b", text=RichText(text="4")),
            Option(id="c", text=RichText(text="5")),
            Option(id="d", text=RichText(text="6")),
        ),
        answer="b",
        marks=1.0,
    )
    gate = (
        GateVerdict(passed=True, rules_version="v2")
        if gated
        else GateVerdict(
            passed=False,
            issues=(
                Issue(
                    code="option_count",
                    message="four options",
                    severity=Severity.ERROR,
                ),
            ),
        )
    )
    explanation = (
        Explanation(
            key_point=RichText(text="Two and two is four."),
            body=RichText(text="Adding two to two gives four."),
            confidence=0.9,
            producer=PRODUCER,
        )
        if explained
        else None
    )
    evidence = Evidence(gate=gate, explanation=explanation)
    item = StagingItem(
        id=item_id,
        provenance=provenance,
        content=content,
        evidence=evidence,
        catalog=(
            CatalogRef(
                exam="JAMB",
                subject="mathematics",
                year=2025,
                topic_id="algebra",
                subtopic_id="surds",
                catalog_version="2026.1",
            )
            if placed
            else None
        ),
        state=state,
        hashes=(
            Hashes(payload_hash="b" * 64, content_hash="c" * 64, bundle_hash="d" * 64)
            if with_hash
            else None
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    if hashed and item.hashes is not None:
        item = item.with_content_hash()
    if not reviewed:
        return item
    # The check is written against the stamped hash, which is the whole
    # point of the column: a check made against other content does not
    # cover this content.
    record = Verification(
        id=f"{item_id}:ai_bulk",
        kind=VerificationKind.AI_BULK,
        verdict=Verdict.PASS,
        scope=("answer", "explanation", "topic_link"),
        content_hash=item.hashes.content_hash if item.hashes else "c" * 64,
        reviewer="nemotron-3-ultra",
        created_at=NOW,
        producer=PRODUCER,
    )
    evidence = item.evidence.model_copy(
        update={"verifications": item.evidence.verifications + (record,)}
    )
    return item.model_copy(update={"evidence": evidence})


def service() -> ReadyService:
    return ReadyService(catalog=catalog())


# ── a bundle that meets every condition ─────────────────────────────────────


def test_a_complete_bundle_is_ready() -> None:
    bundle = service().bundle([make_item()])

    assert bundle.ready is True
    assert bundle.report.satisfied is True
    assert bundle.report.unmet() == ()
    assert bundle.report.total == 1


def test_every_condition_is_reported() -> None:
    bundle = service().bundle([make_item()])

    conditions = [report.condition for report in bundle.report.conditions]

    assert conditions == [
        ReadyCondition.GATED,
        ReadyCondition.REVIEWED,
        ReadyCondition.PLACED,
        ReadyCondition.COMPLETE,
        ReadyCondition.EXPLANATORY,
        ReadyCondition.RESOLVABLE,
        ReadyCondition.IDENTIFIED,
        ReadyCondition.NEW,
    ]


# ── each condition, refused ────────────────────────────────────────────────


def test_a_row_the_gate_refused_is_not_ready() -> None:
    bundle = service().bundle([make_item(gated=False)])

    assert bundle.ready is False
    assert ReadyCondition.GATED in bundle.report.unmet()
    assert "option_count" in bundle.report.reason_for(ReadyCondition.GATED)[0]


def test_a_row_with_no_check_is_not_ready() -> None:
    bundle = service().bundle([make_item(reviewed=False)])

    assert ReadyCondition.REVIEWED in bundle.report.unmet()


def test_a_row_with_no_placement_is_not_ready() -> None:
    bundle = service().bundle([make_item(placed=False)])

    assert ReadyCondition.PLACED in bundle.report.unmet()


def test_a_row_with_no_explanation_is_not_ready() -> None:
    bundle = service().bundle([make_item(explained=False)])

    assert ReadyCondition.EXPLANATORY in bundle.report.unmet()


def test_a_row_with_no_hash_is_not_ready() -> None:
    bundle = service().bundle([make_item(with_hash=False)])

    assert ReadyCondition.IDENTIFIED in bundle.report.unmet()


def test_a_row_whose_content_changed_after_the_check_is_not_ready() -> None:
    """The check that keeps a bundle honest.

    The hash is stamped on the content, and the check covers that hash. Edit
    the content and the stamp no longer matches, which is the whole point of
    the column.
    """
    item = make_item()
    edited = item.model_copy(
        update={
            "content": item.content.model_copy(update={"stem": RichText(text="What is 2 + 3?")})
        }
    )

    bundle = service().bundle([edited])

    assert ReadyCondition.IDENTIFIED in bundle.report.unmet()
    assert "changed" in bundle.report.reason_for(ReadyCondition.IDENTIFIED)[0]


def test_a_subtopic_outside_the_catalog_is_not_ready() -> None:
    item = make_item()
    assert item.catalog is not None
    misplaced = item.model_copy(
        update={"catalog": item.catalog.model_copy(update={"subtopic_id": "not-there"})}
    )

    bundle = service().bundle([misplaced])

    assert ReadyCondition.PLACED in bundle.report.unmet()
    assert "not in the catalog" in bundle.report.reason_for(ReadyCondition.PLACED)[0]


def test_a_subtopic_under_another_topic_is_not_ready() -> None:
    item = make_item()
    assert item.catalog is not None
    misplaced = item.model_copy(
        update={"catalog": item.catalog.model_copy(update={"topic_id": "geometry"})}
    )

    bundle = service().bundle([misplaced])

    assert ReadyCondition.PLACED in bundle.report.unmet()


def test_a_figure_with_a_url_and_a_position_is_resolvable() -> None:
    item = make_item(
        stem_marks=(
            Inline(
                kind=InlineKind.IMAGE,
                start=0,
                len=0,
                url="https://example.com/x.png",
                position=ImagePosition.BELOW,
            ),
        )
    )

    bundle = service().bundle([item])

    assert bundle.ready is True


# ── the counts and the human sign-off ───────────────────────────────────────


def test_the_counts_add_up() -> None:
    bundle = service().bundle([make_item(), make_item(item_id="live:q2")])

    for report in bundle.report.conditions:
        assert report.met + report.unmet == bundle.report.total


def test_the_reasons_are_deduplicated() -> None:
    """Two rows that fail the same way give one line, not two."""
    bundle = service().bundle(
        [
            make_item(item_id="live:q1", explained=False),
            make_item(item_id="live:q2", explained=False),
        ]
    )

    reasons = bundle.report.reason_for(ReadyCondition.EXPLANATORY)

    assert len(reasons) == 1
    assert bundle.report.total == 2


def test_the_human_sign_off_is_counted_and_not_required() -> None:
    """The bank cannot raise this number, so it is reported and not required."""
    bundle = service().bundle([make_item()])

    assert bundle.report.human_signed == 0
    assert bundle.ready is True


def test_a_human_pass_is_counted() -> None:
    item = make_item()
    assert item.hashes is not None
    human = Verification(
        id="live:q1:human",
        kind=VerificationKind.HUMAN,
        verdict=Verdict.PASS,
        scope=("answer", "explanation"),
        content_hash=item.hashes.content_hash,
        reviewer="owner",
        created_at=NOW,
    )
    evidence = item.evidence.model_copy(
        update={"verifications": item.evidence.verifications + (human,)}
    )
    signed = item.model_copy(update={"evidence": evidence})

    bundle = service().bundle([signed])

    assert bundle.report.human_signed == 1
