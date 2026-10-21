"""The audit service. Sample the machine's work, and measure it.

The bank does not ask a person to review the content. It asks them for a
sample, and it turns their verdicts on that sample into the number that
decides how much content can move.

The sample is drawn deterministically, so a run can be repeated and the
same rows come up again. A random sample that changes every run cannot be
audited, because the second look is not the same look.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from utmelab_bank.domain.audit import Agreement, agreement
from utmelab_bank.domain.enums import Verdict
from utmelab_bank.domain.models import StagingItem


class AuditService:
    """Draws a sample of reviewed rows and measures the machine against it."""

    def __init__(self, items: Sequence[StagingItem]) -> None:
        self._items = list(items)

    def sample(self, count: int) -> tuple[StagingItem, ...]:
        """Take a sample of the rows to check.

        The rows are taken evenly across the whole run, from the first to
        the last, so the sample covers the run instead of the first few
        rows of it. The order is the order the rows came in, so the sample
        is the same every run.
        """
        if count <= 0 or not self._items:
            return ()
        if count >= len(self._items):
            return tuple(self._items)
        last = len(self._items) - 1
        picked = [
            self._items[round(index * last / (count - 1))] for index in range(count)
        ]
        return tuple(picked)

    def machine_verdicts(
        self, items: Iterable[StagingItem]
    ) -> tuple[Verdict, ...]:
        """The machine's verdict on each row, from its last verification."""
        verdicts: list[Verdict] = []
        for item in items:
            records = item.evidence.verifications
            verdicts.append(records[-1].verdict if records else Verdict.ABSTAIN)
        return tuple(verdicts)

    def measure(
        self,
        items: Sequence[StagingItem],
        person: Sequence[Verdict],
    ) -> Agreement:
        """Compare the machine's verdicts with the person's on these rows."""
        return agreement(self.machine_verdicts(items), person)


__all__ = ["AuditService"]
