"""status: a read-only snapshot that agrees with the selectors.

The one bug this file exists to keep fixed: ``unverified`` used to look for a
bare ``verifications`` table, which no lane has. A count that raises is worse
than no status at all, so the selector is exercised against real lane tables.
"""

from __future__ import annotations

import json
from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.report.status import collect_status, render_status
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository


async def test_status_on_an_empty_bank(store: Store) -> None:
    report = await collect_status(store, "work", "sqlite::memory:")

    assert report.counts["work"]["questions"] == 0
    assert report.counts["work"]["media"] == 0
    assert report.runs == []
    assert report.media["description failed"] == 0

    text = render_status(report)
    assert "rows" in text
    assert "last runs" in text
    assert "(none)" in text


async def test_status_counts_rows_and_media_queues(
    store: Store,
    question_row: dict[str, Any],
    media_rows: list[dict[str, Any]],
) -> None:
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [question_row])
    await repo.insert_many("media", media_rows)
    await repo.update(
        "media",
        media_rows[0]["id"],
        {
            "description": "a correct description",
            "description_verdict": "pass",
            "status": "described",
        },
    )
    await repo.update(
        "media",
        media_rows[1]["id"],
        {
            "description": "a wrong description",
            "description_verdict": "fail",
            "status": "uploaded",
        },
    )

    report = await collect_status(store, "work", "sqlite::memory:")

    assert report.counts["work"]["questions"] == 1
    assert report.counts["work"]["media"] == 2
    assert report.media_status == {"described": 1, "uploaded": 1}
    assert report.media_verdicts == {"fail": 1, "pass": 1}
    assert report.media["description unchecked"] == 0
    assert report.media["description failed"] == 1
    assert report.media["description verified"] == 1
    assert report.media["needs review"] == 1
    assert report.media["no description"] == 0
    assert report.questions["unverified"] == 1

    text = render_status(report)
    assert "description failed" in text


async def test_unverified_selector_reads_the_lane_verifications_table(
    store: Store,
    question_row: dict[str, Any],
) -> None:
    """The selector used to look for a bare ``verifications`` table."""
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [question_row])
    assert await repo.count("questions", "unverified") == 1

    await repo.insert_many(
        "verifications",
        [
            {
                "id": f"v_{question_row['id']}_human",
                "question_id": question_row["id"],
                "kind": "human",
                "verdict": "pass",
                "scope": json.dumps(["answer", "explanation"]),
                "verifier": "tester",
                "detail": None,
                "content_hash": question_row["content_hash"],
                "created_at": now_iso(),
            }
        ],
    )

    assert await repo.count("questions", "unverified") == 0
