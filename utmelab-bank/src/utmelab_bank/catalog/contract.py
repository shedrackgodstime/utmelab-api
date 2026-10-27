"""Rules a catalog row must satisfy before a question may point at it.

The older contract asked whether a name was non-empty and unique. That let a
whole poem sit in the subtopic table: it was non-empty, it had a slug, and it
had a parent. The tag gate then accepted questions placed under it, because
the id existed.

These rules are about whether a row is *choosable*: short enough to be read,
a phrase rather than a sentence or a list item, and distinguishable from its
siblings without guessing. They are deliberately mechanical. A word list
cannot judge meaning, but it can refuse the shapes that are never meaningful.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: A subtopic is one thing a question is about. Beyond this it is a paragraph
#: or a syllabus description, and a model cannot pick it reliably.
MAX_NAME_CHARS = 120

#: "(a)", "(ii)", "b)", "3." at the start means the parser kept a list marker.
_LIST_MARKER = r"^(?:\((?:\d+|[a-zA-Z]|[ivxIVX]+)\)|(?:\d+|[a-zA-Z]|[ivxIVX]+)[.)])\s+"

#: A name that starts with "(" but is not a marker is a fragment of the
#: sentence that came before it: "(for internal use and for export), ...".
_PAREN_FRAGMENT = r"^\((?![a-zA-Z0-9]+\)\s)"

#: A heading cut before its object: "Problems related to", "Meaning and
#: differences between". The rest became a subtopic, so the topic is a stub.
_DANGLING_END = re.compile(
    r"\b(?:to|of|for|and|or|with|between|includes|including|following|"
    r"are|is|the|in|on|by|as|from|into|that|which)$",
    re.IGNORECASE,
)

#: Prose addressed to the candidate, not a name: "Candidates will be required
#: to answer one question", "The paper will be divided into three sections".
_SENTENCE = re.compile(
    r"\b(?:will be|should be|are required|is required|are advised|"
    r"candidates? (?:are|will|should)|the paper (?:will|is)|this paper (?:will|is))\b",
    re.IGNORECASE,
)

#: A parenthetical that is a cut label or an empty shell: "(Paper 1:)",
#: "(B. Privatisation)", "(S/no contents)". These read as noise to a model.
_BAD_QUALIFIER = re.compile(
    r"\((?:\s*|(?:S/No|Contents?|Notes?|Paper\s+\d+)\b[^()]*|[A-Z]\.\s+[A-Z][A-Za-z ]+)\)",
    re.IGNORECASE,
)

#: A paper label with a colon inside a nested parenthetical.
_PAPER_LABEL = re.compile(r"\bPaper\s+\d+\s*:", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RowDefect:
    """One reason a topic or subtopic cannot be used as a target."""

    subject: str
    slug: str
    kind: str
    rule: str
    detail: str


def name_defects(name: str) -> list[tuple[str, str]]:
    """The shape rules for one name, independent of its siblings."""
    found: list[tuple[str, str]] = []
    if len(name) > MAX_NAME_CHARS:
        found.append(("too_long", f"{len(name)} chars, max {MAX_NAME_CHARS}"))
    if re.match(_LIST_MARKER, name):
        found.append(("list_marker", "starts with a list marker"))
    if re.match(_PAREN_FRAGMENT, name):
        found.append(("fragment", "starts mid-sentence inside a bracket"))
    if name[:1].islower():
        found.append(("lowercase_start", "starts with a lowercase word"))
    dangling = _DANGLING_END.search(name)
    if dangling:
        found.append(("dangling_end", f"ends with {dangling.group(0)!r}"))
    if _SENTENCE.search(name):
        found.append(("sentence", "reads as prose, not a name"))
    if _BAD_QUALIFIER.search(name) or _PAPER_LABEL.search(name):
        found.append(("invalid_qualifier", "a qualifier is a table or paper label"))
    return found


def subject_defects(
    subject: str,
    topics: list[dict[str, Any]],
    subtopics: list[dict[str, Any]],
) -> list[RowDefect]:
    """Every semantic defect in one subject's rows."""
    defects: list[RowDefect] = []
    topic_names: dict[str, str] = {}
    for row in topics:
        slug = str(row.get("slug") or "")
        name = str(row.get("name") or "")
        for rule, detail in name_defects(name):
            defects.append(RowDefect(subject, slug, "topic", rule, f"{name!r}: {detail}"))
        key = name.strip().lower()
        if key in topic_names:
            defects.append(
                RowDefect(
                    subject,
                    slug,
                    "topic",
                    "duplicate_name",
                    f"{name!r} also at {topic_names[key]}",
                )
            )
        else:
            topic_names[key] = slug

    seen: dict[tuple[str, str], str] = {}
    for row in subtopics:
        slug = str(row.get("slug") or "")
        name = str(row.get("name") or "")
        topic = str(row.get("topic") or "")
        for rule, detail in name_defects(name):
            defects.append(RowDefect(subject, slug, "subtopic", rule, f"{name!r}: {detail}"))
        sub_key = (topic, name.strip().lower())
        if sub_key in seen:
            defects.append(
                RowDefect(
                    subject,
                    slug,
                    "subtopic",
                    "duplicate_name",
                    f"{name!r} also under {seen[sub_key]}",
                )
            )
        else:
            seen[sub_key] = slug
    return defects


def summarise(defects: list[RowDefect]) -> dict[tuple[str, str], int]:
    """Counts keyed by subject and rule, for the build report."""
    counts: dict[tuple[str, str], int] = {}
    for defect in defects:
        key = (defect.subject, defect.rule)
        counts[key] = counts.get(key, 0) + 1
    return counts


__all__ = [
    "MAX_NAME_CHARS",
    "RowDefect",
    "name_defects",
    "subject_defects",
    "summarise",
]
