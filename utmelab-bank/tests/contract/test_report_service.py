"""Contract tests for the report consumer and the drift check.

These are the two ways content comes back. A report says the content is
wrong, and drift says the check on it is stale.
"""

from datetime import UTC, datetime
from typing import Any, Optional

import pytest

from utmelab_bank.adapters.drift_service import DriftService
from utmelab_bank.adapters.report_service import ReportService
from utmelab_bank.adapters.store.reports import ReportLogStore
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.state import can_transition
from utmelab_bank.domain.models import (
    Content,
    Hashes,
    Option,
    Provenance,
    RichText,
    Scope,
    StagingItem,
)
from utmelab_bank.domain.reports import Drift, Report, ReportReason, ReportTarget

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
HASH = "c" * 64


class FakeClient:
    """A tiny in-memory report log."""

    def __init__(self) -> None:
        self.rows: list[tuple[Any, ...]] = []
        self.statements: list[str] = []

    async def execute(
        self,
        statement: str,
        args: Optional[list[Any]] = None,
        *,
        commit: Optional[bool] = None,
    ) -> Any:
        self.statements.append(statement)
        values = args or []

        class Result:
            def __init__(self, rows: list[tuple[Any, ...]]) -> None:
                self.rows = rows

        if "INSERT OR REPLACE INTO report_log" in statement:
            self.rows.append(tuple(values))
            return Result([])
        if "SELECT report_id FROM report_log" in statement:
            return Result([(row[0],) for row in self.rows])
        if "count(*) FROM report_log" in statement:
            return Result([(len(self.rows),)])
        return Result([])


def make_item(
    *,
    item_id: str = "live:q1",
    state: State = State.LIVE,
    content_hash: str = HASH,
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
        stem=RichText(text="What is 2 + 2?"),
        options=(
            Option(id="a", text=RichText(text="3")),
            Option(id="b", text=RichText(text="4")),
            Option(id="c", text=RichText(text="5")),
            Option(id="d", text=RichText(text="6")),
        ),
        answer="b",
        marks=1.0,
    )
    return StagingItem(
        id=item_id,
        provenance=provenance,
        content=content,
        state=state,
        hashes=Hashes(
            payload_hash="b" * 64,
            content_hash=content_hash,
            bundle_hash="d" * 64,
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def make_report(
    *,
    report_id: str = "rpt_1",
    target_id: str = "live:q1",
    reason: str = ReportReason.WRONG_ANSWER,
    detail: Optional[str] = "the answer should be 4",
) -> Report:
    return Report(
        id=report_id,
        target_type=ReportTarget.QUESTION,
        target_id=target_id,
        reporter="a-key",
        reason=reason,
        detail=detail,
        created_at=NOW,
    )


# ── the report log ──────────────────────────────────────────────────────────


async def test_a_report_is_seen_once() -> None:
    log = ReportLogStore(FakeClient())
    service = ReportService(log)
    report = make_report()

    first = await service.new_reports([report])
    await service.record(report, item_id="live:q1")
    second = await service.new_reports([report])

    assert len(first) == 1
    assert len(second) == 0


async def test_the_log_counts_what_it_has_seen() -> None:
    log = ReportLogStore(FakeClient())

    await log.record(make_report())

    assert await log.count() == 1


# ── reopening a row the bank placed ────────────────────────────────────────


def test_a_live_row_is_reopened_and_goes_back_to_the_bench() -> None:
    service = ReportService(ReportLogStore(FakeClient()))
    item = make_item()

    reopened = service.reopen(item, make_report())

    assert reopened.state is State.ENRICHED
    assert reopened.error is not None
    assert "wrong_answer" in reopened.error
    assert "the answer should be 4" in reopened.error


def test_a_row_that_is_not_live_cannot_be_reopened() -> None:
    service = ReportService(ReportLogStore(FakeClient()))

    with pytest.raises(ValueError, match="only a live row"):
        service.reopen(make_item(state=State.VERIFIED), make_report())


# ── claiming a row the bank did not place ───────────────────────────────────


def test_a_claimed_row_goes_into_the_pipeline_again() -> None:
    service = ReportService(ReportLogStore(FakeClient()))
    item = make_item(state=State.ACQUIRED)

    claimed = service.claim(item, make_report())

    assert claimed.state is State.ADAPTED


def test_a_claimed_row_must_start_acquired() -> None:
    service = ReportService(ReportLogStore(FakeClient()))

    with pytest.raises(ValueError, match="starts acquired"):
        service.claim(make_item(state=State.LIVE), make_report())


# ── drift ───────────────────────────────────────────────────────────────────


def test_a_drifted_row_is_found() -> None:
    service = DriftService()
    item = make_item()

    drifts = service.find([item], {item.provenance.source_item_id: "d" * 64})

    assert len(drifts) == 1
    assert drifts[0].question_id == "q1"
    assert drifts[0].expected == HASH
    assert drifts[0].found == "d" * 64
    assert drifts[0].drifted is True


def test_a_row_that_did_not_change_is_not_drift() -> None:
    service = DriftService()
    item = make_item()

    assert service.find([item], {item.provenance.source_item_id: HASH}) == ()


def test_a_row_that_is_not_live_is_not_compared() -> None:
    service = DriftService()
    item = make_item(state=State.READY)

    assert service.find([item], {item.provenance.source_item_id: "d" * 64}) == ()


def test_a_row_production_no_longer_holds_is_not_drift() -> None:
    """It is gone, not moved. The item is left alone."""
    service = DriftService()
    item = make_item()

    assert service.find([item], {}) == ()


def test_a_drifted_row_goes_back_to_the_bench() -> None:
    service = DriftService()
    item = make_item()
    drift = Drift(question_id=item.id, expected=HASH, found="d" * 64)

    reopened = service.reopen(item, drift)

    assert reopened.state is State.ENRICHED
    assert reopened.error is not None
    assert "drifted" in reopened.error


def test_the_drift_check_sees_the_stale_check_not_the_content() -> None:
    """The content is fine. What is stale is the check on it.

    So the row goes back to enriched, where the content is looked at again,
    rather than to the start.
    """
    service = DriftService()
    item = make_item()
    drift = Drift(question_id=item.id, expected=HASH, found="d" * 64)

    reopened = service.reopen(item, drift)

    assert reopened.state is State.ENRICHED
    assert can_transition(State.ENRICHED, State.VERIFIED)
