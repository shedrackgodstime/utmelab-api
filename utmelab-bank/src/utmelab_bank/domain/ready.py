"""Ready. What a bundle has to be before it can be placed.

**Ready is a definition, not a writer.** The bank does not place content in
the served tables, so what it owes is a bundle that is complete enough that
placing it is a mechanical step for whoever does that.

Eight conditions, and each one is checkable by machine:

| Condition | What it means |
|---|---|
| Gated | Every rule ran, and the refusals are counted. |
| REVIEWED | A check covers the answer and the explanation, at the hash of the content as it stands. Whose check it is does not matter here. |
| PLACED | The subtopic exists in the catalog, under the right exam and subject. |
| COMPLETE | A stem, options, an answer that names one of them, a difficulty, and marks. |
| EXPLANATORY | An explanation with a key point and a body. |
| RESOLVABLE | Every stimulus the question needs is there, and every figure has a url and a position. |
| IDENTIFIED | The hash matches the content as it stands now. |
| NEW | Nothing in the bundle duplicates anything already held. |

**The human sign-off is not one of the eight**, because the bank cannot give
it. Only a person can, and the serving predicate counts only a person. So the
report says how many rows carry a human pass, and the person decides what to
do about the number.
"""

from __future__ import annotations

from enum import StrEnum

from .models.common import DomainModel, NonEmptyStr, StagingItem


class ReadyCondition(StrEnum):
    """The eight conditions a bundle has to meet."""

    GATED = "gated"
    REVIEWED = "reviewed"
    PLACED = "placed"
    COMPLETE = "complete"
    EXPLANATORY = "explanatory"
    RESOLVABLE = "resolvable"
    IDENTIFIED = "identified"
    NEW = "new"


class ConditionReport(DomainModel):
    """How one condition fared across the bundle.

    ``met`` and ``unmet`` count the rows. ``reasons`` says why the rows that
    did not meet it did not, one line per distinct reason, so the bundle
    says what is missing rather than only how much.
    """

    condition: ReadyCondition
    met: int
    unmet: int
    reasons: tuple[NonEmptyStr, ...] = ()

    @property
    def satisfied(self) -> bool:
        """Whether every row met this condition."""
        return self.unmet == 0


class ReadyReport(DomainModel):
    """The whole bundle's readiness, condition by condition.

    ``human_signed`` is how many rows carry a human pass. The bank cannot
    raise it, and the serving predicate counts only it, so it is reported
    rather than required.
    """

    conditions: tuple[ConditionReport, ...] = ()
    human_signed: int = 0
    total: int = 0

    @property
    def satisfied(self) -> bool:
        """Whether every condition is met for every row."""
        return all(report.satisfied for report in self.conditions)

    def unmet(self) -> tuple[ReadyCondition, ...]:
        """The conditions that are not met."""
        return tuple(report.condition for report in self.conditions if not report.satisfied)

    def reason_for(self, condition: ReadyCondition) -> tuple[str, ...]:
        """Why a condition was not met."""
        for report in self.conditions:
            if report.condition is condition:
                return report.reasons
        return ()


class ReadyBundle(DomainModel):
    """The output. The rows, and the report that says where they stand."""

    items: tuple[StagingItem, ...] = ()
    report: ReadyReport

    @property
    def ready(self) -> bool:
        """Whether the bundle can be placed without further judgement."""
        return self.report.satisfied


__all__ = [
    "ConditionReport",
    "ReadyBundle",
    "ReadyCondition",
    "ReadyReport",
]
