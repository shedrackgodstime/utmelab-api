"""The report log. Which reports the bank has already acted on.

A report is acted on once. Recording that it was seen is what stops the
same complaint opening the same work every time the reports are read.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from utmelab_bank.domain.reports import Report


class ReportLogStore:
    """Reads and writes the bank's record of the reports it has acted on."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def seen(self) -> frozenset[str]:
        """The ids of the reports the bank has already acted on."""
        result = await self._client.execute("SELECT report_id FROM report_log")
        return frozenset(str(row[0]) for row in result.rows)

    async def unseen(self, reports: tuple[Report, ...]) -> tuple[Report, ...]:
        """The reports the bank has not acted on yet."""
        done = await self.seen()
        return tuple(report for report in reports if report.id not in done)

    async def record(self, report: Report, *, item_id: str | None = None) -> None:
        """Record that a report was acted on, and on what."""
        await self._client.execute(
            """
            INSERT OR REPLACE INTO report_log (
                report_id, target_type, target_id, reason, item_id, acted_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                report.id,
                report.target_type,
                report.target_id,
                report.reason,
                item_id,
                datetime.now(UTC).isoformat(),
            ],
        )

    async def count(self) -> int:
        """How many reports the bank has acted on."""
        result = await self._client.execute("SELECT count(*) FROM report_log")
        return int(result.rows[0][0])


__all__ = ["ReportLogStore"]
