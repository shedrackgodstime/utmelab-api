"""A live contract test: the reports and the drift check must work.

The server owns the reports table and the questions table, and the bank
reads both. So this reads the real reports, checks the real hashes, and
proves the two services work against the real data.

It is skipped unless ``UTMELAB_LIVE=1`` is set, because it needs the network.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest

from utmelab_bank.adapters.database import bank_client, prod_client
from utmelab_bank.adapters.drift_service import DriftService
from utmelab_bank.adapters.production import (
    ProductionContentReader,
    ProductionReportReader,
)
from utmelab_bank.adapters.report_service import ReportService
from utmelab_bank.adapters.store.reports import ReportLogStore
from utmelab_bank.adapters.store.staging import StagingStore
from utmelab_bank.config import load_settings
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import (
    Content,
    Hashes,
    Option,
    Provenance,
    RichText,
    Scope,
    StagingItem,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("UTMELAB_LIVE") != "1",
        reason="set UTMELAB_LIVE=1 to run live provider smoke tests",
    ),
]


def _rich(raw: dict[str, Any]) -> RichText:
    return RichText.model_validate(
        {"text": raw["text"], "inline": raw.get("inline") or []}
    )


async def test_the_reports_are_read_and_acted_on_once() -> None:
    settings = load_settings()
    bank = bank_client(settings)
    prod = prod_client(settings)
    await StagingStore(bank).prepare()

    reports = await ProductionReportReader(prod).reports()
    log = ReportLogStore(bank)
    service = ReportService(log)

    # Every report is either new or already acted on. Which one depends on
    # what the bank did before, so the test states the invariant rather than
    # a number that moves.
    seen = await log.seen()
    new = await service.new_reports(reports)
    assert len(new) + len([r for r in reports if r.id in seen]) == len(reports)

    for report in reports:
        await service.record(report, item_id=None)

    again = await service.new_reports(reports)

    assert len(again) == 0
    assert await log.count() >= len(reports)


async def test_the_drift_check_compares_against_what_production_holds() -> None:
    """The hashes the bank checks against are the ones production holds."""
    settings = load_settings()
    prod = prod_client(settings)
    reader = ProductionContentReader(prod)

    hashes = await reader.hashes()
    known = await reader.known()

    assert len(hashes) == len(known)
    for question in known:
        assert hashes[question.question_id] == question.content_hash


async def test_a_drifted_row_is_found_against_the_real_hashes() -> None:
    settings = load_settings()
    prod = prod_client(settings)
    reader = ProductionContentReader(prod)
    hashes = await reader.hashes()
    service = DriftService()

    now = datetime.now(UTC)
    question_id = next(iter(hashes))
    live = StagingItem(
        id=f"live:{question_id}",
        provenance=Provenance(
            source="live",
            source_url="https://production.invalid/x",
            source_item_id=question_id,
            fetched_at=now,
            payload_hash="b" * 64,
            source_version="1",
            scope=Scope(exam="JAMB", subject="mathematics", year=2025),
        ),
        content=Content(
            stem=RichText(text="What is 2 + 2?"),
            options=(
                Option(id="a", text=RichText(text="3")),
                Option(id="b", text=RichText(text="4")),
            ),
            answer="b",
            marks=1.0,
        ),
        state=State.LIVE,
        hashes=Hashes(
            payload_hash="b" * 64, content_hash="0" * 64, bundle_hash="d" * 64
        ),
        created_at=now,
        updated_at=now,
    )

    drifts = service.find([live], hashes)

    assert len(drifts) == 1
    assert drifts[0].expected == "0" * 64
    assert drifts[0].found == hashes[question_id]
    assert drifts[0].drifted is True


async def test_a_live_row_that_matches_is_not_drift() -> None:
    settings = load_settings()
    prod = prod_client(settings)
    reader = ProductionContentReader(prod)
    hashes = await reader.hashes()
    service = DriftService()

    now = datetime.now(UTC)
    question_id = next(iter(hashes))
    live = StagingItem(
        id=f"live:{question_id}",
        provenance=Provenance(
            source="live",
            source_url="https://production.invalid/x",
            source_item_id=question_id,
            fetched_at=now,
            payload_hash="b" * 64,
            source_version="1",
            scope=Scope(exam="JAMB", subject="mathematics", year=2025),
        ),
        content=Content(
            stem=RichText(text="What is 2 + 2?"),
            options=(
                Option(id="a", text=RichText(text="3")),
                Option(id="b", text=RichText(text="4")),
            ),
            answer="b",
            marks=1.0,
        ),
        state=State.LIVE,
        hashes=Hashes(
            payload_hash="b" * 64,
            content_hash=hashes[question_id],
            bundle_hash="d" * 64,
        ),
        created_at=now,
        updated_at=now,
    )

    assert service.find([live], hashes) == ()
