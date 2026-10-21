"""The gate. Strict, machine only, and total.

The gate runs on every row and the default is fail. Every rule that can
detect a defect can block a row, and a blocked row does not leave the bank.
That is deliberate: the serving side does not validate content, so a bad row
either breaks an endpoint for every consumer or is served as a wrong answer.
The gate is the only place either can be stopped.

Two kinds of refusal, and the difference matters.

A **defect** is objective. A mark that runs past the end of its text, an answer
that names no option, an unknown subtopic, a duplicate hash. The normal
resolution is a fix to the content.

A **judgement** is a case the machine cannot settle. The figure hint is the
one that bites, because "table" is both a display and an ordinary word. The
row is refused, the refusal names the rule, and a person says why it is fine.

**Both go to the same person, and both are resolved the same way.** The gate
refuses, and the person either fixes the content or records a clearance with
a reason. The severity stays on the issue, so the counts still say what was
objectively broken and what needed judgement, but there is one queue and one
mechanism, and nothing leaves the bank without a person having looked at it.

The rules are the live ones from ``tools/review.py``, which is the tool that
writes today's verification records. The archived tree's import rules are
different, and they are not the ones in force.

No I/O here. Everything the gate needs arrives in the context.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from .enums import Severity
from .models.common import (
    CatalogRef,
    CatalogSnapshot,
    Clearance,
    Content,
    GateVerdict,
    Issue,
    Mark,
)

#: Bumped when a rule changes meaning, so a verdict can be traced to the
#: rules that produced it.
RULES_VERSION = "v2"

#: The word hints that mean a question is about a figure. These collide with
#: ordinary English, which is why the rule judges rather than refuses.
FIGURE_HINTS: tuple[tuple[str, bool, bool], ...] = (
    ("diagram", True, False),
    ("figure", False, False),
    ("graph", True, False),
    ("illustrat", False, True),
    ("shown", False, False),
    ("sketch", True, False),
    ("table", False, False),
)

#: Strings that mean a question was lifted from a novel and leaked into the
#: question bank.
NOVEL_MARKERS: tuple[str, ...] = ("bepo", "stardom", "lekki")

#: Phrases that mark a numbered gap in a cloze passage.
GAP_MARKERS: tuple[str, ...] = (
    "gap labelled",
    "gap numbered",
    "gaps labelled",
    "gaps numbered",
)

#: An HTML entity, or a tag. The loader refuses both rather than serving
#: mojibake to a student.
_ENTITY = re.compile(r"&[a-zA-Z]+;")
_TAG = re.compile(r"<[a-zA-Z/!]")

#: The option ids the live bank uses.
_OPTION_IDS = ("a", "b", "c", "d", "e")


@dataclass(frozen=True)
class GateContext:
    """Everything the gate needs to judge one row.

    The catalog is optional because a row can be judged for its own shape
    before it has been placed. The known sets are how the gate sees the rest
    of the bank and of production, so a duplicate is caught by the gate
    rather than by a later step.
    """

    content: Content
    exam: str = ""
    subject: str = ""
    year: Optional[int] = None
    placement: Optional[CatalogRef] = None
    catalog: Optional[CatalogSnapshot] = None
    known_ids: frozenset[str] = frozenset()
    known_hashes: frozenset[str] = frozenset()
    known_near_duplicates: frozenset[str] = frozenset()
    known_passage_ids: frozenset[str] = frozenset()
    self_id: Optional[str] = None
    self_hash: Optional[str] = None
    clearances: tuple[Clearance, ...] = field(default_factory=tuple)


def near_duplicate_fingerprint(stem: str, option_texts: Iterable[str]) -> str:
    """The fingerprint that catches a reworded duplicate.

    Not the content hash. The content hash never collides, so it only ever
    catches a row copied verbatim, and a verbatim copy is not the duplicate
    that actually happens. This is the live rule from ``tools/review.py``:
    the lowercased stem plus the sorted lowercased option texts, joined, and
    hashed to sixteen hex characters.
    """
    options = sorted(text.strip().lower() for text in option_texts)
    joined = stem.strip().lower() + "|" + "~".join(options)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def mentions_figure(text: str) -> bool:
    """Whether the text refers to a figure, by word boundary.

    Per hint strictness: figure and table are exact words, because both
    double as ordinary words. diagram, graph and sketch tolerate a plural.
    illustrat is a prefix stem. shown is exact.
    """
    lower = text.lower()
    for hint, plural, prefix in FIGURE_HINTS:
        start = 0
        while True:
            pos = lower.find(hint, start)
            if pos < 0:
                break
            before_ok = pos == 0 or not (
                lower[pos - 1].isalpha() or lower[pos - 1] == "-"
            )
            run = 0
            index = pos + len(hint)
            while index < len(lower) and (lower[index].isalpha() or lower[index] == "-"):
                run += 1
                index += 1
            if prefix:
                after_ok = True
            elif run == 0:
                after_ok = True
            else:
                after_ok = plural and run == 1 and lower[pos + len(hint)] == "s"
            if before_ok and after_ok:
                return True
            start = pos + 1
    return False


def has_numbered_gap(text: str) -> bool:
    """Whether the text names a numbered gap, which needs a passage."""
    lower = text.lower()
    for marker in GAP_MARKERS:
        rest = lower
        while marker in rest:
            rest = rest.split(marker, 1)[1]
            stripped = rest.strip()
            index = 0
            while index < len(stripped) and stripped[index].isdigit():
                index += 1
            if index > 0:
                return True
    return False


def _error(code: str, message: str, field_name: Optional[str] = None) -> Issue:
    return Issue(code=code, message=message, severity=Severity.ERROR, field=field_name)


def _judgement(code: str, message: str, field_name: Optional[str] = None) -> Issue:
    return Issue(
        code=code, message=message, severity=Severity.JUDGEMENT, field=field_name
    )


def check_marks(
    text: str, marks: tuple[Mark, ...], label: str, issues: list[Issue]
) -> None:
    """The rules every piece of text carries.

    Bounds are checked in Unicode characters, the same count the marks use.
    Two marks may share an identical range, and a partial overlap is refused.

    The rule takes the text and the marks separately, so it can be judged on
    its own. The model refuses an out of bounds mark and a partial overlap
    first, so in normal operation this is the second line, not the first.
    """
    length = len(text)
    for index, mark in enumerate(marks):
        if mark.start + mark.len > length:
            issues.append(
                _error(
                    "mark_out_of_bounds",
                    f"{label} mark {index} (start {mark.start}, len {mark.len}) "
                    f"runs past the end of {length} characters",
                    label,
                )
            )
        if mark.kind.value == "image":
            if mark.url is None or not mark.url.startswith("https://"):
                issues.append(
                    _error(
                        "image_url_not_https",
                        f"{label} mark {index} has image url {mark.url!r}, "
                        "which must be absolute https",
                        label,
                    )
                )
            if mark.len != 0:
                issues.append(
                    _error(
                        "image_mark_not_anchor",
                        f"{label} mark {index} is an image, so its length must "
                        "be zero",
                        label,
                    )
                )

    order = sorted(range(len(marks)), key=lambda i: (marks[i].start, marks[i].len))
    for first, second in zip(order, order[1:]):
        a = marks[first]
        b = marks[second]
        identical = b.start == a.start and b.len == a.len
        if b.start < a.start + a.len and not identical:
            issues.append(
                _error(
                    "mark_partial_overlap",
                    f"{label} mark (start {b.start}, len {b.len}) partially "
                    f"overlaps (start {a.start}, len {a.len})",
                    label,
                )
            )


def check_plain_text(text: str, label: str, issues: list[Issue]) -> None:
    """No HTML entity and no markup.

    The loader refuses both rather than serving mojibake to a student, so the
    rule here is the same refusal.
    """
    if _ENTITY.search(text):
        issues.append(
            _error(
                "html_in_text",
                f"{label} carries an HTML entity, which must be unescaped at "
                "the source",
                label,
            )
        )
    if _TAG.search(text):
        issues.append(
            _error(
                "html_in_text",
                f"{label} carries markup, which must be stripped at the source",
                label,
            )
        )


def check_option_ids(
    option_ids: Sequence[str], answer: str, issues: list[Issue]
) -> None:
    """The option ids are a to e, unique, and the answer names one of them."""
    if len(set(option_ids)) != len(option_ids):
        issues.append(
            _error("option_id_duplicate", "option ids must be unique", "options")
        )
    for option_id in option_ids:
        if option_id not in _OPTION_IDS:
            issues.append(
                _error(
                    "option_id_not_known",
                    f"option id {option_id!r} is not one of a to e",
                    "options",
                )
            )
    if answer not in option_ids:
        issues.append(
            _error(
                "answer_not_an_option",
                f"the answer {answer!r} names none of the options",
                "answer",
            )
        )


def check_option_count(count: int, issues: list[Issue]) -> None:
    """Exactly four options, which is the live rule."""
    if count != 4:
        issues.append(
            _error(
                "option_count",
                f"the question has {count} options, and the live rule is "
                "exactly four",
                "options",
            )
        )


def _check_stem(content: Content, issues: list[Issue]) -> None:
    stem = content.stem
    if not stem.text.strip():
        issues.append(_error("stem_empty", "the stem has no text", "text"))
    check_marks(stem.text, stem.marks, "text", issues)
    check_plain_text(stem.text, "text", issues)

    lower = stem.text.lower()
    if "underlin" in lower and not any(
        mark.kind.value == "underline" for mark in stem.marks
    ):
        issues.append(
            _judgement(
                "underline_missing",
                "the stem mentions underlining but carries no underline mark",
                "text",
            )
        )
    if mentions_figure(stem.text) and not any(
        mark.kind.value == "image" for mark in stem.marks
    ):
        issues.append(
            _judgement(
                "missing_figure",
                "the stem refers to a figure but carries no image mark",
                "text",
            )
        )


def _check_options(content: Content, issues: list[Issue]) -> None:
    options = content.options
    check_option_count(len(options), issues)
    check_option_ids([option.id for option in options], content.answer, issues)
    for option in options:
        if not option.text.text.strip():
            issues.append(
                _error(
                    "option_text_empty",
                    f"option {option.id!r} has no text",
                    "options",
                )
            )
        check_marks(option.text.text, option.text.marks, f"option {option.id!r}", issues)
        check_plain_text(option.text.text, f"option {option.id!r}", issues)

    blob = (content.stem.text + " " + " ".join(o.text.text for o in options)).lower()
    for marker in NOVEL_MARKERS:
        if marker in blob:
            issues.append(
                _judgement(
                    "novel_leak",
                    f"the question carries novel content ({marker!r})",
                    "text",
                )
            )


def _check_explanation(content: Content, issues: list[Issue]) -> None:
    explanation = content.source_explanation
    if explanation is None:
        issues.append(
            _error(
                "explanation_missing",
                "the question has no explanation, and a question without one "
                "cannot be reviewed",
                "explanation",
            )
        )
        return
    check_marks(explanation.text, explanation.marks, "explanation", issues)
    check_plain_text(explanation.text, "explanation", issues)


def _check_numbers(context: GateContext, issues: list[Issue]) -> None:
    if not context.exam:
        issues.append(
            _error("exam_empty", "the question names no exam", "exam")
        )
    if context.year is not None and not 1900 <= context.year <= 2100:
        issues.append(
            _error(
                "year_out_of_range",
                f"the year {context.year} is outside 1900 to 2100",
                "year",
            )
        )
    if not 0.5 <= context.content.marks <= 10.0:
        issues.append(
            _error(
                "marks_out_of_range",
                f"the marks {context.content.marks} are outside 0.5 to 10",
                "marks",
            )
        )


def _check_placement(context: GateContext, issues: list[Issue]) -> None:
    """The catalog is the placement authority, so a placement is checked
    against it and never invented."""
    catalog = context.catalog
    placement = context.placement
    if placement is None:
        return
    if placement.exam != context.exam or placement.subject != context.subject:
        issues.append(
            _error(
                "placement_scope_mismatch",
                f"the placement names {placement.subject!r} for "
                f"{placement.exam!r}, but the row is {context.subject!r} for "
                f"{context.exam!r}",
                "subtopic_id",
            )
        )
        return
    if catalog is None:
        return
    if catalog.exam != context.exam or catalog.subject != context.subject:
        issues.append(
            _error(
                "catalog_scope_mismatch",
                f"the catalog is for {catalog.subject!r} for {catalog.exam!r}, "
                f"not {context.subject!r} for {context.exam!r}",
                "subtopic_id",
            )
        )
        return
    subtopic = next(
        (s for s in catalog.subtopics if s.slug == placement.subtopic_id), None
    )
    if subtopic is None:
        issues.append(
            _error(
                "subtopic_not_in_catalog",
                f"the subtopic {placement.subtopic_id!r} is not in the catalog",
                "subtopic_id",
            )
        )
        return
    topic = next(
        (t for t in catalog.topics if t.id == subtopic.topic_id),
        None,
    )
    if topic is None:
        issues.append(
            _error(
                "subtopic_topic_missing",
                f"the subtopic {placement.subtopic_id!r} points at an unknown "
                "topic",
                "subtopic_id",
            )
        )
        return
    if topic.slug != placement.topic_id:
        issues.append(
            _error(
                "subtopic_topic_mismatch",
                f"the subtopic {placement.subtopic_id!r} sits under "
                f"{topic.slug!r}, not {placement.topic_id!r}",
                "subtopic_id",
            )
        )


def _check_passage(context: GateContext, issues: list[Issue]) -> None:
    content = context.content
    if content.passage is None:
        if has_numbered_gap(content.stem.text):
            issues.append(
                _judgement(
                    "cloze_without_passage",
                    "the stem names a numbered gap but the question has no "
                    "passage",
                    "passage",
                )
            )
        return
    if context.known_passage_ids and content.passage.id not in context.known_passage_ids:
        issues.append(
            _error(
                "passage_not_found",
                f"the passage {content.passage.id!r} does not exist",
                "passage",
            )
        )
    check_marks(
        content.passage.text.text, content.passage.text.marks, "passage", issues
    )
    check_plain_text(content.passage.text.text, "passage", issues)


def _check_duplicates(context: GateContext, issues: list[Issue]) -> None:
    if context.self_id is not None and context.self_id in context.known_ids:
        issues.append(
            _error(
                "duplicate_id",
                f"the id {context.self_id!r} is already held",
                "id",
            )
        )
    if context.self_hash is not None and context.self_hash in context.known_hashes:
        issues.append(
            _error(
                "duplicate_content",
                "the content hash is already held, so this is the same content",
                "content",
            )
        )
    fingerprint = near_duplicate_fingerprint(
        context.content.stem.text,
        (option.text.text for option in context.content.options),
    )
    if fingerprint in context.known_near_duplicates:
        issues.append(
            _judgement(
                "duplicate_near",
                "the question is a near-duplicate of one already held",
                "content",
            )
        )


def run_gate(context: GateContext) -> GateVerdict:
    """Run every rule over one row and return the verdict.

    The verdict passes when every issue it raised has been cleared by a
    person. The unresolved issues are the person's queue.
    """
    issues: list[Issue] = []
    _check_stem(context.content, issues)
    _check_options(context.content, issues)
    _check_explanation(context.content, issues)
    _check_numbers(context, issues)
    _check_placement(context, issues)
    _check_passage(context, issues)
    _check_duplicates(context, issues)

    clearances = context.clearances
    cleared = {clearance.rule for clearance in clearances}
    unresolved = any(issue.code not in cleared for issue in issues)
    return GateVerdict(
        passed=not unresolved,
        issues=tuple(issues),
        clearances=clearances,
        rules_version=RULES_VERSION,
    )


def refusal_counts(verdicts: Iterable[GateVerdict]) -> dict[str, int]:
    """How many rows each rule refused.

    The count per rule is how a weak source becomes visible, and it is the
    only number that says which rule to tighten next.
    """
    counts: dict[str, int] = {}
    for verdict in verdicts:
        for issue in verdict.issues:
            counts[issue.code] = counts.get(issue.code, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


__all__ = [
    "FIGURE_HINTS",
    "GAP_MARKERS",
    "NOVEL_MARKERS",
    "RULES_VERSION",
    "GateContext",
    "check_marks",
    "check_option_count",
    "check_option_ids",
    "check_plain_text",
    "has_numbered_gap",
    "mentions_figure",
    "near_duplicate_fingerprint",
    "refusal_counts",
    "run_gate",
]
