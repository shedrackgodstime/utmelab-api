"""Free, deterministic checks. Every row passes these before any token is spent."""

from __future__ import annotations

from utmelab_bank.rules import MIN_PASSAGE_CHARS, GateVerdict, judge, judge_row
from utmelab_bank.task.gates.dedupe import Dedupe
from utmelab_bank.task.gates.mechanical import MechanicalGate
from utmelab_bank.task.gates.media_presence import MediaPresence

__all__ = [
    "MIN_PASSAGE_CHARS",
    "Dedupe",
    "GateVerdict",
    "MechanicalGate",
    "MediaPresence",
    "judge",
    "judge_row",
]
