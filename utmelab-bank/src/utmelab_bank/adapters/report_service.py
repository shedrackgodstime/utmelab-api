"""The report service. A complaint becomes work.

The server serves a report endpoint and owns the table. A report is a
consumer saying that something in the served bank is wrong, with one of five
reasons and the detail they gave.

The bank reads the reports and turns each new one into work. There are two
cases, and they are different.

**The bank placed the row.** The row is one of the bank's, and it is
already live. So it is reopened: live to reported, and reported back to
enriched, where the content is looked at again.

**The bank did not place the row.** It is production's content, from
elsewhere. The bank takes ownership of it: a new item is opened, sourced
from production, carrying what the report said, and it goes through the
whole pipeline as a fresh row.

Either way the report is recorded, so the same complaint does not open the
same work twice.
"""

from __future__ import annotations

from collections.abc import Iterable

from utmelab_bank.adapters.store.reports import ReportLogStore
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import StagingItem
from utmelab_bank.domain.reports import Report

#: Where the bank sources a row it did not place.
PRODUCTION_SOURCE = "production"


class ReportService:
    """Reads the reports and turns the new ones into work."""

    def __init__(self, log: ReportLogStore) -> None:
        self._log = log

    async def new_reports(self, reports: Iterable[Report]) -> tuple[Report, ...]:
        """The reports the bank has not acted on."""
        return await self._log.unseen(tuple(reports))

    def reopen(self, item: StagingItem, report: Report) -> StagingItem:
        """Reopen a row the bank placed, because a consumer reported it.

        The reason and the detail are kept on the item, so the person who
        looks at it next can see what was complained about.
        """
        if item.state is not State.LIVE:
            raise ValueError(f"only a live row can be reopened, and this one is {item.state.value}")
        description = _describe(report)
        reported = item.transition_to(State.REPORTED, error=description)
        # The complaint is still the reason this row is on the bench, so the
        # note travels with it.
        return reported.transition_to(State.ENRICHED, error=description)

    def claim(self, item: StagingItem, report: Report) -> StagingItem:
        """Take ownership of a row the bank did not place.

        The row becomes a fresh item, sourced from production, with the
        report's reason and detail on it. It goes through the whole
        pipeline from the start, because nothing about it has been checked
        yet.
        """
        if item.state is not State.ACQUIRED:
            raise ValueError(f"a claimed row starts acquired, and this one is {item.state.value}")
        return item.transition_to(State.ADAPTED)

    async def record(self, report: Report, *, item_id: str | None = None) -> None:
        """Record that a report was acted on."""
        await self._log.record(report, item_id=item_id)


def _describe(report: Report) -> str:
    """The one line that says what was complained about."""
    if report.detail:
        return f"reported {report.reason}: {report.detail}"
    return f"reported {report.reason}"


__all__ = ["PRODUCTION_SOURCE", "ReportService"]
