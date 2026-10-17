"""Free, deterministic checks. Every row passes these before any token is spent."""

from __future__ import annotations

from utmelab_bank.rules import GateVerdict, MIN_PASSAGE_CHARS, judge, judge_row
from utmelab_bank.task.gates.dedupe import Dedupe
from utmelab_bank.task.gates.media_presence import MediaPresence
from utmelab_bank.task.gates.mechanical import MechanicalGate

__all__ = [
    "Dedupe",
    "GateVerdict",
    "MIN_PASSAGE_CHARS",
    "MechanicalGate",
    "MediaPresence",
    "judge",
    "judge_row",
]
