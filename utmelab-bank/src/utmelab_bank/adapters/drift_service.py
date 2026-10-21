"""The drift service. The row that moved under the check.

The bank stamped a hash on the content and the check covered that hash. If
what production holds now has a different hash, the content moved, and the
check no longer says anything about it.

Production notices this too. Its serving predicate compares the row's hash
with the one the verification covered, and a row that drifted falls out of
service until someone verifies it again. That is the mechanism working.

The bank does the same comparison against the rows it placed, and puts the
drifted ones back on the bench, so a row that lost its verification comes
back as work instead of as a silent loss of coverage.
"""

from __future__ import annotations

from collections.abc import Iterable

from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import StagingItem
from utmelab_bank.domain.reports import Drift


class DriftService:
    """Compares what the bank placed with what production holds."""

    def find(self, items: Iterable[StagingItem], production: dict[str, str]) -> tuple[Drift, ...]:
        """The live rows that no longer match what the bank checked.

        Only rows the bank placed are compared, because only those have a
        hash the bank stamped. A row that has since been removed from
        production is not drift, it is gone, and the item is left alone.

        The lookup is by the source item id, not by the staging id. The
        staging id is ``source:source_item_id`` so two sources cannot
        collide, and production keys its rows by the bare id.
        """
        drifts: list[Drift] = []
        for item in items:
            if item.state is not State.LIVE:
                continue
            if item.hashes is None or not item.hashes.content_hash:
                continue
            found = production.get(item.provenance.source_item_id)
            if found is None:
                continue
            drift = Drift(
                question_id=item.provenance.source_item_id,
                expected=item.hashes.content_hash,
                found=found,
            )
            if drift.drifted:
                drifts.append(drift)
        return tuple(drifts)

    def reopen(self, item: StagingItem, drift: Drift) -> StagingItem:
        """Put a drifted row back on the bench.

        The row goes straight to enriched, because the content itself is
        fine. What is stale is the check, so the content is looked at again
        and checked again.
        """
        if item.state is not State.LIVE:
            raise ValueError(f"only a live row can drift, and this one is {item.state.value}")
        return item.transition_to(
            State.ENRICHED,
            error=(
                f"drifted: the checked hash {drift.expected[:12]} is not the "
                f"one production holds, {drift.found[:12]}"
            ),
        )


__all__ = ["DriftService"]
