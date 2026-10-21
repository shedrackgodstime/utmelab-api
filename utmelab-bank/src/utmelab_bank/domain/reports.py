"""Reports and drift. The two ways content comes back.

**A report** is a consumer saying that something in the served bank is
wrong. The server owns the table, and the reasons are its five: a wrong
answer, an unclear stem, a broken option, a wrong explanation, and other.
A report is evidence, not a verdict. It says the content deserves a look,
and what the look should be about.

**Drift** is the served content no longer matching what the bank checked.
The bank stamped a hash on the content and the check covered that hash, so
if what production holds has a different hash, the content moved under the
check. Production notices this too: its serving predicate compares the two
hashes, and a row that drifted falls out of service until someone verifies
it again. The bank's job is to notice it first and put the row back on the
bench.

Both end in the same place. The content is reworked, checked again, and
becomes ready again.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional

from .models.common import DomainModel, NonEmptyStr, Sha256


class ReportReason(StrEnum):
    """Why a consumer reported a row. The values are the server's."""

    WRONG_ANSWER = "wrong_answer"
    UNCLEAR_STEM = "unclear_stem"
    BROKEN_OPTION = "broken_option"
    WRONG_EXPLANATION = "wrong_explanation"
    OTHER = "other"


class ReportTarget(StrEnum):
    """What a report is about.

    The server's table is target agnostic, so the bank is too. A report
    about something that is not a question is still a report.
    """

    QUESTION = "question"
    PASSAGE = "passage"


class Report(DomainModel):
    """One report, as the server holds it."""

    id: NonEmptyStr
    target_type: NonEmptyStr
    target_id: NonEmptyStr
    reporter: NonEmptyStr
    reason: NonEmptyStr
    detail: Optional[NonEmptyStr] = None
    created_at: datetime


class Drift(DomainModel):
    """A row in production that no longer matches what the bank checked.

    ``expected`` is the hash the bank checked. ``found`` is the hash
    production holds now. When they differ, the content moved under the
    check, and the row has to be looked at again.
    """

    question_id: NonEmptyStr
    expected: Sha256
    found: Sha256

    @property
    def drifted(self) -> bool:
        """Whether the two hashes differ."""
        return self.expected != self.found


__all__ = [
    "Drift",
    "Report",
    "ReportReason",
    "ReportTarget",
]
