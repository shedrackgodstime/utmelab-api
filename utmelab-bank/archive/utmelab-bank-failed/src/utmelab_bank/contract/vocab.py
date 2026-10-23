"""Every closed value set, in one file.

The API's ``verified_predicate`` in ``src/store/catalog.rs`` names
``kind='human'``, ``verdict='pass'``, and the scope values ``answer`` and
``explanation`` inside a SQL string. We write those columns. So the value sets
are shared vocabulary, and they belong in one file where a change is one edit
rather than a hunt through six task modules.

``pipeline_status`` and ``ai_status`` are ours alone, and they drifted apart
inside the pipeline: the metrics collector counted
``flagged_for_review`` while the repository wrote ``ready_for_review``. Both
names are listed here, with ``ready_for_review`` marked current, so the drift is
visible rather than latent.
"""

from __future__ import annotations

from typing import Final, Literal

__all__ = [
    "AI_STATUS",
    "EXAM",
    "GATE_REASON",
    "PASSAGE_KIND",
    "PIPELINE_STATUS",
    "PIPELINE_STATUS_CURRENT",
    "PIPELINE_STATUS_RETIRED",
    "SCOPE",
    "VERDICT",
    "VERIFICATION_SCOPE_NEEDED",
    "VERIFIER_KIND",
]

VERIFIER_KIND: Final[tuple[str, ...]] = (
    "human",
    "ai_describe",
    "ai_explain",
    "ai_tag",
    "ai_verify",
    "ai_bulk",
)

VERDICT: Final[tuple[str, ...]] = ("pass", "fail", "disagree", "ambiguous")

SCOPE: Final[tuple[str, ...]] = (
    "answer",
    "explanation",
    "passage",
    "subtopic",
    "media",
    "formatting",
)

#: The two the API's verified predicate requires. A human pass without both
#: leaves the question unverified, silently.
VERIFICATION_SCOPE_NEEDED: Final[frozenset[str]] = frozenset({"answer", "explanation"})

#: A row in the work lane. ``ready_for_review`` is the name the writer uses and
#: the name the metrics must count. ``flagged_for_review`` is what the pipeline's
#: collector counted and nothing ever wrote; kept only so the mismatch is
#: visible in one place.
PIPELINE_STATUS: Final[tuple[str, ...]] = (
    "harvested",
    "validated",
    "ready_for_review",
    "approved_for_prod",
    "synced_to_prod",
    "refused",
)
PIPELINE_STATUS_CURRENT: Final[str] = "ready_for_review"
PIPELINE_STATUS_RETIRED: Final[str] = "flagged_for_review"

AI_STATUS: Final[tuple[str, ...]] = ("unprocessed", "running", "done", "refused", "skipped")

EXAM: Final[tuple[str, ...]] = ("jamb", "waec", "neco")

PASSAGE_KIND: Final[tuple[str, ...]] = ("Comprehension", "Data", "Reading")

#: Why a row was refused at the gate. A closed set so a metric can group by it
#: and so a new reason is a deliberate addition rather than a typo.
#:
#: The last four are the quarantine rules from ``utmelab-api-old/src/quarantine.rs``
#: that were missing here: a stem that points at an underline it does not carry,
#: an option count the exam does not use, a novel leaking into the subject bank,
#: and a second row claiming one content fingerprint. Each was a rule the archive
#: enforced and this did not, which is 11 committed rows and one live novel
#: question later.
GATE_REASON: Final[tuple[str, ...]] = (
    "few_options",
    "too_many_options",
    "duplicate_options",
    "answer_not_an_option",
    "option_count_for_exam",
    "option_count_unknown_exam",
    "missing_referenced_figure",
    "underline_missing",
    "novel_leak",
    "promised_stimulus_absent",
    "empty_stem",
    "stem_too_short",
    "duplicate_fingerprint",
)

GateReason = Literal[
    "few_options",
    "too_many_options",
    "duplicate_options",
    "answer_not_an_option",
    "option_count_for_exam",
    "option_count_unknown_exam",
    "missing_referenced_figure",
    "underline_missing",
    "novel_leak",
    "promised_stimulus_absent",
    "empty_stem",
    "stem_too_short",
    "duplicate_fingerprint",
]
