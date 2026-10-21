"""The gate service. Judge a row, and move it on or refuse it.

The rules live in ``domain.gate`` and are pure. This is the part that knows
about a staging item, the state machine, and what the bank already holds.

The flow is one way. A row that passes the gate moves to ``gated``. A row
that does not is refused, with the reason kept on the item, so the count per
rule is visible and a weak source can be found.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from utmelab_pipeline.domain.enums import State
from utmelab_pipeline.domain.gate import (
    GateContext,
    refusal_counts,
    run_gate,
)
from utmelab_pipeline.domain.models import (
    CatalogRef,
    CatalogSnapshot,
    Clearance,
    GateVerdict,
    StagingItem,
)


class GateService:
    """Run the gate over staging items.

    The known sets are the bank's view of the world. They are passed in
    rather than fetched here, because reading them is an adapter's job and
    the gate itself does no I/O.
    """

    def __init__(
        self,
        *,
        known_ids: Iterable[str] = (),
        known_hashes: Iterable[str] = (),
        known_near_duplicates: Iterable[str] = (),
        known_passage_ids: Iterable[str] = (),
        catalog: Optional[CatalogSnapshot] = None,
        clearances: Optional[dict[str, Sequence[Clearance]]] = None,
    ) -> None:
        self._known_ids = frozenset(known_ids)
        self._known_hashes = frozenset(known_hashes)
        self._known_near_duplicates = frozenset(known_near_duplicates)
        self._known_passage_ids = frozenset(known_passage_ids)
        self._catalog = catalog
        self._clearances = dict(clearances or {})
        #: How many rows each rule refused, after the last run.
        self.last_counts: dict[str, int] = {}

    def context_for(self, item: StagingItem) -> GateContext:
        """The context for one item, built from what the service knows.

        The exam, subject and year come from the provenance scope, because
        that is where the source says the content came from. The placement is
        separate: it says where in the catalog the content sits, and it can
        be absent while the content is still judged for its own shape.
        """
        scope = item.provenance.scope
        placement: Optional[CatalogRef] = item.catalog
        content_hash = item.hashes.content_hash if item.hashes else None
        return GateContext(
            content=item.content,
            exam=scope.exam,
            subject=scope.subject,
            year=scope.year,
            placement=placement,
            catalog=self._catalog,
            known_ids=self._known_ids,
            known_hashes=self._known_hashes,
            known_near_duplicates=self._known_near_duplicates,
            known_passage_ids=self._known_passage_ids,
            self_id=item.id,
            self_hash=content_hash,
            clearances=tuple(self._clearances.get(item.id, ())),
        )

    def judge(self, item: StagingItem) -> GateVerdict:
        """The verdict for one item, without moving it."""
        return run_gate(self.context_for(item))

    def apply(self, item: StagingItem) -> StagingItem:
        """Judge one item and move it on or refuse it.

        A refused row keeps its reason, so the run can report which rule
        refused what, and the item stays in the bank with the count.
        """
        verdict = self.judge(item)
        if verdict.passed:
            return item.transition_to(State.GATED)
        return item.transition_to(State.REJECTED, error=self._summary(verdict))

    def apply_all(self, items: Iterable[StagingItem]) -> list[StagingItem]:
        """Judge many items and report the counts per rule."""
        judged = [self.apply(item) for item in items]
        self.last_counts = refusal_counts(
            [self.judge(item) for item in items]
        )
        return judged

    @staticmethod
    def _summary(verdict: GateVerdict) -> str:
        codes = ", ".join(sorted({issue.code for issue in verdict.issues}))
        return f"{verdict.rules_version}: {codes}"


__all__ = ["GateService"]
