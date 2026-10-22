"""The audit. The number that decides how much content can move.

A person cannot review a hundred thousand questions, so the bank does not
ask them to. It asks them for a **sample**, and it measures how far the
machine's verdicts agree with theirs on that sample.

**The agreement rate is the output.** It is not a score for the model and it
is not a score for the content. It is the number that says how far the
machine can be believed, and a policy threshold says how far it has to be.

Two ways the machine and the person can disagree, and they are not the same
thing:

- The machine **passed** what the person **failed**. The content is wrong
  and the machine missed it. This is the dangerous one.
- The machine **failed** what the person **passed**. The content is fine and
  the machine was strict. This one costs effort, not trust.

So the agreement rate is reported alongside the split, because a rate of
ninety percent that is all in the second direction is not the same as ninety
percent the other way.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .enums import Verdict


@dataclass(frozen=True)
class Agreement:
    """How far the machine and the person agreed on a sample."""

    checked: int
    agreed: int
    missed: int
    over_strict: int

    @property
    def rate(self) -> float:
        """The share they agreed on, from 0 to 1."""
        if self.checked == 0:
            return 0.0
        return self.agreed / self.checked

    @property
    def miss_rate(self) -> float:
        """The share the machine passed and the person failed.

        This is the dangerous one. It is the rate at which wrong content
        would have been let through.
        """
        if self.checked == 0:
            return 0.0
        return self.missed / self.checked

    def __str__(self) -> str:
        if self.checked == 0:
            return "no sample was checked"
        return (
            f"{self.agreed}/{self.checked} agreed "
            f"({self.rate:.1%}), {self.missed} missed, "
            f"{self.over_strict} over strict"
        )


def agreement(machine: Iterable[Verdict], person: Iterable[Verdict]) -> Agreement:
    """Compare the machine's verdicts with the person's on a sample.

    A verdict of abstain is neither a pass nor a fail, so it is counted as
    an agreement only when the person abstained too. An abstention is a
    statement that neither of them could decide, and treating it as a pass
    would be a lie.
    """
    machine_verdicts = list(machine)
    person_verdicts = list(person)
    if len(machine_verdicts) != len(person_verdicts):
        raise ValueError(
            "the machine and the person checked "
            f"{len(machine_verdicts)} and {len(person_verdicts)} rows"
        )

    agreed = 0
    missed = 0
    over_strict = 0
    for theirs, ours in zip(machine_verdicts, person_verdicts, strict=True):
        if theirs is ours:
            agreed += 1
        elif theirs is Verdict.PASS and ours is not Verdict.PASS:
            missed += 1
        elif theirs is not Verdict.PASS and ours is Verdict.PASS:
            over_strict += 1
    return Agreement(
        checked=len(machine_verdicts),
        agreed=agreed,
        missed=missed,
        over_strict=over_strict,
    )


__all__ = ["Agreement", "agreement"]
