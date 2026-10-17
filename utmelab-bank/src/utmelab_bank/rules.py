"""The mechanical rules, as a module of their own.

These decide whether a question is worth anything, and two things need them:
``task.gates.mechanical``, which records a verdict on a work row, and
``task.intake``, which applies them before a raw row is allowed to become a work
row at all.

They live here rather than inside the gate because a task may not import another
task, and a rule is not a task. It has no lane, no run envelope and no side
effects, which is exactly why it is worth being separate.

The rules are not new. They are the union of what four harvesters, a pipeline
gate module and a review tool each decided on their own, with the disagreements
resolved: figure hints come from one regex, the passage floor is one number, and
a refusal reason is one of a closed set so a metric can group by it.
"""

from __future__ import annotations

import json
from typing import Any, Final

from utmelab_bank.contract.vocab import GATE_REASON
from utmelab_bank.errors import BankError
from utmelab_bank.text import has_numbered_gap, mentions_cloze, mentions_figure, promises_stimulus

__all__ = [
    "GATE_REASON",
    "GateVerdict",
    "MAX_OPTIONS",
    "MIN_OPTIONS",
    "MIN_PASSAGE_CHARS",
    "MIN_STEM_CHARS",
    "NOVEL_VOCABULARY",
    "OPTION_COUNTS",
    "is_novel_leak",
    "judge",
    "names_underline",
]

#: How many options a question may have, per exam era. Ported from
#: ``quarantine.rs`` (``len() != 4``) and ``pipeline/gates/mechanical.py``
#: (``not in (4, 5)`` for the exams that use five). A range is not the same rule
#: as an era rule, and a range let eleven committed rows through.
OPTION_COUNTS: Final[dict[str, frozenset[int]]] = {
    "jamb": frozenset({4}),
    "waec": frozenset({4, 5}),
    "neco": frozenset({4, 5}),
}

#: Novel vocabulary sitting in the subject bank (D35). Three proper nouns, from
#: ``quarantine.rs`` and mirrored in ``tools/review.py``. A live scrape found one
#: on the first page of English 2025, which is why this is enforced at intake
#: rather than only reported.
NOVEL_VOCABULARY: Final[tuple[str, ...]] = ("bepo", "stardom", "lekki")

#: The word a stem uses when it is pointing at a mark.
UNDERLINE_WORD: Final[str] = "underlin"

#: A passage below this is a parsing accident, not a stimulus. The harvester and
#: the pipeline disagreed (200 characters against a length check on the stem), so
#: the number lives here once.
MIN_PASSAGE_CHARS: Final[int] = 200

#: Shortest stem we will accept. Below this it is a fragment of a page.
MIN_STEM_CHARS: Final[int] = 12

MIN_OPTIONS: Final[int] = 2
MAX_OPTIONS: Final[int] = 10


class GateVerdict:
    """One row's verdict. A list because a row can fail more than one rule."""

    __slots__ = ("figures", "inline_stimulus", "promises_stimulus", "reasons")

    def __init__(self) -> None:
        self.reasons: list[str] = []
        self.figures: list[str] = []
        self.promises_stimulus = False
        #: Whether the stem carries its own stimulus, which removes the need for
        #: a passage link. See :func:`judge`.
        self.inline_stimulus = False

    @property
    def passed(self) -> bool:
        return not self.reasons

    @property
    def reason(self) -> str:
        """The first reason, which is the one worth reporting.

        Ordered by how fundamental the failure is, so a row with no options is
        reported as having no options rather than as being too short.
        """
        return self.reasons[0] if self.reasons else ""

    def add(self, reason: str) -> None:
        """Record a refusal.

        A reason outside the closed set is a programming error rather than a
        data problem, so it raises. That way a metric can group by the reason
        without a catch-all bucket swallowing the new ones.
        """
        if reason not in GATE_REASON:
            raise BankError("unknown gate reason", reason=reason, known=list(GATE_REASON))
        if reason not in self.reasons:
            self.reasons.append(reason)


def names_underline(text: str) -> bool:
    """Whether the stem is pointing at a mark it does not carry.

    ``quarantine.rs`` calls this ``names_underline``: the stem contains the word
    "underlined" and there is no underline. A candidate reads "choose the word
    opposite the underlined one" and finds nothing to be opposite, so it is
    refused rather than shipped.
    """
    return UNDERLINE_WORD in text.lower()


def is_novel_leak(text: str, option_texts: list[str] | None = None) -> str | None:
    """The novel a row has leaked from, or ``None``.

    The stem and every option are searched, because a novel name often appears
    in an option rather than the stem.
    """
    blob = " ".join([text, *(option_texts or [])]).lower()
    return next((word for word in NOVEL_VOCABULARY if word in blob), None)


def judge(
    *,
    text: str,
    option_ids: list[str],
    answer: str,
    marks: list[dict[str, Any]] | None = None,
    option_texts: list[str] | None = None,
    exam: str | None = None,
    has_passage: bool = False,
    inline_stimulus_chars: int = MIN_PASSAGE_CHARS,
) -> GateVerdict:
    """Apply every mechanical rule to one row.

    ``option_ids`` are the labels the answer points at, taken from the option
    rows rather than derived from their text. Deriving a letter from the first
    character of each option text is what made the old importers disagree with
    the review tool about which rows had a valid key.
    """
    verdict = GateVerdict()
    labels = [label.strip().upper() for label in option_ids]

    if len(labels) < MIN_OPTIONS:
        verdict.add("few_options")
    if len(labels) > MAX_OPTIONS:
        verdict.add("too_many_options")
    if len(set(labels)) != len(labels):
        verdict.add("duplicate_options")
    if answer.strip().upper() not in set(labels):
        verdict.add("answer_not_an_option")

    # The era rule, when we know the exam. An unknown exam gets the range, which
    # is the weaker check and is recorded as such on the verdict.
    allowed = OPTION_COUNTS.get((exam or "").lower())
    if allowed is not None:
        if len(labels) not in allowed:
            verdict.add("option_count_for_exam")
    elif len(labels) not in (4, 5):
        verdict.add("option_count_unknown_exam")

    if is_novel_leak(text, option_texts):
        verdict.add("novel_leak")

    stripped = text.strip()
    if not stripped:
        verdict.add("empty_stem")
    elif len(stripped) < MIN_STEM_CHARS:
        verdict.add("stem_too_short")

    verdict.figures = [
        str(mark.get("url"))
        for mark in (marks or [])
        if mark.get("kind") == "image" and mark.get("url")
    ]
    verdict.promises_stimulus = promises_stimulus(stripped)

    if mentions_figure(stripped) and not verdict.figures:
        verdict.add("missing_referenced_figure")

    if names_underline(stripped) and not any(
        mark.get("kind") == "underline" for mark in (marks or [])
    ):
        verdict.add("underline_missing")

    # A stem that carries its own stimulus does not need a passage link. This
    # exemption is not an optimisation, it is the difference between refusing
    # the bank and shipping it.
    #
    # Arabic, French, Hausa and Igbo comprehension put the whole passage in the
    # stem. Measured over the committed bank, the rule without this exemption
    # refuses 49 rows and 34 of them are stems of 200 characters or more, which
    # is exactly those inline-stem questions. They are answerable. They were
    # recovered on purpose on 2026-10-14 and written to passages.json.
    verdict.inline_stimulus = len(stripped) >= inline_stimulus_chars
    if has_numbered_gap(stripped) or mentions_cloze(stripped):
        if not has_passage:
            verdict.add("promised_stimulus_absent")
    elif verdict.promises_stimulus and not has_passage and not verdict.inline_stimulus:
        verdict.add("promised_stimulus_absent")

    return verdict


def load_json_column(row: dict[str, Any], column: str, fallback: Any) -> Any:
    """Read a json text column, falling back when it is absent or unparseable.

    Every task reads the same four json columns and every one of them can hold
    something that is not json, because a raw row arrives from a scraper. Three
    separate copies of this helper was one too many.
    """
    import json

    value = row.get(column)
    if value in (None, ""):
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return fallback
    return value


def option_ids_of(row: dict[str, Any]) -> list[str]:
    """The option labels on a question row, in order."""
    entries = load_json_column(row, "options", [])
    return [
        str(entry.get("id", "")) if isinstance(entry, dict) else str(entry)
        for entry in entries
    ]


def marks_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The marks on a question row."""
    marks = load_json_column(row, "inline", [])
    return [mark for mark in marks if isinstance(mark, dict)]


def option_texts_of(row: dict[str, Any]) -> list[str]:
    """The option texts on a question row, for the novel leak search."""
    entries = load_json_column(row, "options", [])
    texts: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        body = entry.get("text")
        texts.append(str(body.get("text", "")) if isinstance(body, dict) else str(body))
    return texts


def judge_row(row: dict[str, Any]) -> GateVerdict:
    """Apply the rules to a database row, whatever lane it is in.

    The exam comes off the row rather than being a parameter, so a row that
    arrived claiming to be WAEC is judged by the WAEC rule even when the crawler
    thought otherwise.
    """
    return judge(
        text=str(row.get("text") or ""),
        option_ids=option_ids_of(row),
        answer=str(row.get("answer") or ""),
        marks=marks_of(row),
        option_texts=option_texts_of(row),
        exam=str(row.get("exam") or "") or None,
        has_passage=bool(row.get("passage_id")),
    )


def refuse(row: dict[str, Any]) -> tuple[str, str]:
    """Return (status, reason) for a row: ("pass", "") or ("refused", reason)."""
    verdict = judge_row(row)
    if verdict.passed:
        return ("pass", "")
    return ("refused", verdict.reason)


# Backwards-compatible alias for tests
judge_raw = judge_row
