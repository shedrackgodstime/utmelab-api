"""Turn positioned PDF lines into topics and subtopics.

Every topic owns a vertical band: from its heading down to the next heading.
A body line belongs to the band it sits in, not to whichever heading happened
to be read before it. That one rule makes single-column syllabuses and
two-column tables parse the same way, and it stops maths notes from leaking
into the next topic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .contract import MAX_NAME_CHARS, name_defects
from .model import Subtopic, Syllabus, Topic
from .pdf import Line
from .profiles import STOP_MARKERS, Profile

#: Two printed lines within this vertical distance are on the same row.
ROW_TOLERANCE = 3.5

#: A sentence that ends with one of these was not a sentence boundary.
_ABBREVIATION = re.compile(
    r"(?:\be\.g|\bi\.e|\betc|\bvs|\bNo|\bDr|\bMr|\bMrs|\bMs|\bFig|\bSt|\b[0-9])\.$",
    re.IGNORECASE,
)


class ParseError(RuntimeError):
    """The PDF did not have the shape the profile promised."""


@dataclass(frozen=True, slots=True)
class _Heading:
    index: int
    line: Line
    name: str
    consumed: frozenset[int] = frozenset()


#: A list marker that the PDF printed in front of a name: "(a)", "(ii)", "b)",
#: "3.". Decimal numbers keep their dot ("1.0"), so a dot needs a space after it.
_NAME_MARKER = re.compile(
    r"^(?:\*+\s*"
    r"|\((?:\d{1,2}|[a-zA-Z]|[ivxIVX]{1,5})\)\s*"
    r"|(?:\d{1,2}|[a-zA-Z]|[ivxIVX]{1,5})[.)]\s+)+"
)


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().lstrip("*").strip()
    text = re.sub(r"(?<=\w)-\s+(?=[A-Za-z])", "-", text)
    return text.rstrip(".")


def _tidy_name(text: str) -> str:
    text = re.sub(r"[•∗♦♣♠]+", " ", text)
    text = _NAME_MARKER.sub("", text)
    text = re.sub(r"\b\d+\s*\|\s*P\s*a\s*g\s*e\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bP\s*a\s*g\s*e\s*\|\s*\d+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,;:.])", r"\1", text)
    text = text.rstrip(" .,:;–—-").strip()
    # "(Homeostasis)" wraps a heading in brackets; the brackets are layout.
    if text.startswith("(") and text.endswith(")") and text.count("(") == 1:
        text = text[1:-1].strip()
    # "(For all candidates) The paper ..." is an audience note in front of the
    # real heading, not part of its name.
    text = re.sub(r"^\([^)]{2,60}\)\s+(?=\S)", "", text).strip()
    if not text:
        return text
    # The source prints many table entries in lower case ("definition,").
    # Raising the first letter is typography, not a change of words.
    return text[:1].upper() + text[1:]


#: A list that continues inside one printed line: "Cell ... (ii) Tissue ...
#: (iii) Organ ...". Splitting at (ii) onward keeps every item verbatim.
_INLINE_MARKER = re.compile(r"\s+(?=\((?:ii|iii|iv|v|vi|vii|viii|ix|x|[b-h])\)\s)")


def _split_inline(text: str) -> list[str]:
    return [part.strip() for part in _INLINE_MARKER.split(text) if part.strip()]


def _sentences(text: str) -> list[str]:
    # A prose topic that numbers its parts (a), (b) is already segmented; use
    # those markers before guessing at sentence boundaries.
    marker = r"\((?:[a-z]|[ivx]{1,4})\)\s"
    if len(re.findall(rf"(?<![A-Za-z]){marker}", text)) >= 2:
        return [part.strip() for part in re.split(rf"(?={marker})", text) if part.strip()]
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    merged: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if merged and _ABBREVIATION.search(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def _segment(body: list[Line], profile: Profile) -> list[str]:
    """Split a topic body into subtopics without changing its words."""
    if not body:
        return []
    if profile.subtopic_re is None:
        text = _clean(" ".join(line.text for line in body))
        if not text:
            return []
        return _sentences(text) if profile.sentence_split else [text]

    marker = re.compile(profile.subtopic_re)
    pieces: list[str] = []
    current: list[str] = []
    for line in body:
        match = marker.match(line.text)
        if match:
            if current:
                pieces.append(_clean(" ".join(current)))
            current = [match.group(2)]
        else:
            current.append(line.text)
    if current:
        pieces.append(_clean(" ".join(current)))

    if not pieces:
        text = _clean(" ".join(line.text for line in body))
        return _sentences(text) if profile.sentence_split else ([text] if text else [])
    return pieces


def _is_heading_continuation(text: str, limit: int, *, allow_upper: bool = False) -> bool:
    """A wrapped heading is short and does not end like a sentence."""
    words = text.split()
    if re.match(r"^(?:\(\w+\)|[A-Za-z0-9]+[.)])\s", text):
        return False
    if text.startswith(("•", "-", "–", "—")):
        return False
    if text.strip().upper() in {"CONTENTS", "NOTES", "S/NO CONTENTS"}:
        return False
    return (
        len(words) <= limit
        and not text.rstrip().endswith((".", ";", ":"))
        and not text.upper().startswith("NOTE")
        and (allow_upper or not (len(words) > 1 and text.upper() == text))
    )


def _stop_topic_name(name: str, profile: Profile) -> str:
    """Cut a topic heading at the label that starts its body.

    Some PDFs print the heading and the body on one line ("Books of Original
    Entry Definition, purpose..."). The heading is the part before the body
    label. Never cut before the heading has at least two words.
    """
    if profile.topic_name_stop_re is None:
        return name
    match = re.search(profile.topic_name_stop_re, name)
    if match is None:
        return name
    prefix = name[: match.start()].strip()
    return prefix if prefix else name


def _incomplete(name: str) -> bool:
    stripped = name.rstrip()
    if stripped.endswith(("-", "–", "—")):
        return True
    return (
        stripped.rstrip(".;:")
        .lower()
        .endswith(
            (
                " and",
                " of",
                " for",
                " to",
                " in",
                " on",
                " with",
                " the",
                " between",
                " following",
            )
        )
    )


def _strip_topic_marker(name: str) -> str:
    return _NAME_MARKER.sub("", name).strip()


def _scope(lines: list[Line], profile: Profile) -> list[Line]:
    start = 0
    for index, line in enumerate(lines):
        if profile.start_marker.lower() in line.text.lower():
            start = index + 1
            break
    stop = len(lines)
    for index in range(start, len(lines)):
        if _is_stop_heading(lines[index].text):
            stop = index
            break
    scope: list[Line] = []
    for line in lines[start:stop]:
        text = line.text.strip()
        if not text or text.isdigit():
            continue
        if (
            "Sierra Leone USA" in text
            or "French Speaking territories" in text
            or text.startswith("The Gambia Ghana Liberia")
        ):
            continue
        if text.upper() in {
            "CONTENTS NOTES",
            "CONTENT NOTES",
            "TOPICS NOTES",
            "CONTENTS",
            "CONTENT",
            "TOPIC",
            "TOPICS",
            "NOTES",
            "S/N",
            "S/NO",
            "S/NO.",
        }:
            continue
        scope.append(line)
    return scope


def _is_stop_heading(text: str) -> bool:
    """A reading list or practical list is a heading, not body prose."""
    upper = re.sub(r"^[\s.0-9()\-–—]+", "", text.upper())
    if len(upper.split()) > 8:
        return False
    return any(upper == marker or upper.startswith(marker) for marker in STOP_MARKERS)


def _bands(scope: list[Line], profile: Profile) -> list[_Heading]:
    topic_re = re.compile(profile.topic_re)
    section_re = re.compile(profile.section_re)
    headings: list[_Heading] = []
    for index, line in enumerate(scope):
        following = scope[index + 1] if index + 1 < len(scope) else None
        if not (profile.topic_x_min <= line.x <= profile.topic_x_max):
            continue
        if section_re.match(line.text):
            continue
        if profile.heading_heuristic:
            if not _looks_like_heading(
                line,
                following,
                allow_uppercase=profile.allow_uppercase_headings,
            ):
                continue
            name = _stop_topic_name(_clean(line.text), profile)
            if profile.strip_topic_markers:
                name = _strip_topic_marker(name)
            if name:
                headings.append(_Heading(index=index, line=line, name=name))
            continue
        match = topic_re.match(line.text)
        if not match:
            continue
        raw = match.group("name") if "name" in match.re.groupindex else match.group(2)
        name = _stop_topic_name(_clean(raw), profile)
        if profile.strip_topic_markers:
            name = _strip_topic_marker(name)
        if name or profile.bare_marker_topics:
            headings.append(_Heading(index=index, line=line, name=name))
    return _merge_incomplete_headings(headings, profile)


def _merge_incomplete_headings(headings: list[_Heading], profile: Profile) -> list[_Heading]:
    """Join a heading split over two printed lines (FUNDAMENTALS OF / COMPUTER)."""
    merged: list[_Heading] = []
    for heading in headings:
        previous = merged[-1] if merged else None
        wrapped = False
        if previous is not None:
            wrapped = 0 < heading.index - previous.index <= 3 and (
                _incomplete(previous.name)
                or (
                    abs(heading.line.x - previous.line.x) <= 30
                    and len(previous.name.split()) >= 2
                    and len(heading.name.split()) == 1
                )
            )
        if (
            previous is not None
            and wrapped
            and heading.line.x <= profile.topic_x_max
            and _is_heading_continuation(heading.line.text, profile.topic_continuation_words)
        ):
            merged[-1] = _Heading(
                index=previous.index,
                line=previous.line,
                name=_clean(f"{previous.name} {heading.name}"),
                consumed=previous.consumed | {id(heading.line)} | heading.consumed,
            )
            continue
        merged.append(heading)
    return merged


def _looks_like_heading(
    line: Line, following: Line | None, *, allow_uppercase: bool = False
) -> bool:
    """An unnumbered heading is a short title, not a proofread sentence.

    A country or artist entry under a heading is followed by a dash-indented
    gloss; that makes it body, not a heading of its own.
    """
    text = line.text.strip()
    if not text or text.isdigit():
        return False
    if text[0] in "(–—-":
        return False
    if text.endswith((".", ";", ":", ",")):
        return False
    words = text.split()
    if len(words) > 8:
        return False
    if text.upper().startswith("NOTE"):
        return False
    if not allow_uppercase and text.upper() == text and len(words) > 1:
        return False
    if allow_uppercase:
        core = re.sub(r"^[A-Za-z]\.\s+", "", text)
        core = re.sub(r"\s*\(\d+ marks?\)$", "", core)
        if core.upper() != core:
            return False
    if not (text[0].isupper() or text[0].isdigit()):
        return False
    if following is not None:
        next_text = following.text.strip()
        if following.x > 200 and next_text.startswith(("-", "–", "—")):
            return False
    return True


def _in_band(candidate: Line, heading: _Heading, following: _Heading | None) -> bool:
    """Is the line between this heading and the next one?"""
    start = heading.line
    if candidate.page == start.page:
        if candidate.y > start.y + ROW_TOLERANCE:
            return False
        if following is not None and following.line.page == start.page:
            return candidate.y > following.line.y + ROW_TOLERANCE
        return True
    if candidate.page < start.page:
        return False
    if following is None:
        return True
    if candidate.page < following.line.page:
        return True
    if candidate.page == following.line.page:
        return candidate.y > following.line.y + ROW_TOLERANCE
    return False


def _is_continuation(
    line: Line,
    heading: _Heading,
    profile: Profile,
    *,
    seen_body: bool,
    current_name: str | None = None,
    closed: bool = False,
) -> bool:
    if closed or profile.topic_continuation_x_max is None:
        return False
    if line.x > profile.topic_continuation_x_max:
        return False
    if not _is_heading_continuation(
        line.text,
        profile.topic_continuation_words,
        allow_upper=(profile.topic_continuation_same_x or profile.allow_uppercase_continuations),
    ):
        return False
    if profile.subtopic_re and re.match(profile.subtopic_re, line.text):
        return False
    if (
        profile.uppercase_continuation_in_body
        and not seen_body
        and line.text.isupper()
        and len(line.text.split()) <= 4
    ):
        return True
    in_progress = current_name if current_name is not None else heading.name
    if _incomplete(in_progress) and len(line.text.split()) <= 6:
        return True
    # An indented lower-case line directly under the heading continues it:
    # "3. Meaning and differences between" / "subsistence and commercial
    # agriculture". Once a subtopic marker has appeared, body lines are closed.
    if (
        not seen_body
        and heading.line.x <= line.x <= heading.line.x + profile.topic_continuation_gap
        and line.text[:1].islower()
    ):
        return True
    # A heading in the left column can wrap while the notes column, to its
    # right, is already printing body text on the same row. That body text
    # does not close the heading: it is a different column. Once body has
    # started, only an uppercase continuation (a heading fragment) may join;
    # a title-case subheading belongs to the body.
    if (
        profile.body_x_min > 0
        and line.x < profile.body_x_min
        and heading.line.x <= line.x <= heading.line.x + profile.topic_continuation_gap
        and len(line.text.split()) <= 4
        and (not seen_body or line.text.isupper())
    ):
        return True
    if (
        profile.body_x_min > 0
        and line.x >= profile.body_x_min
        and not profile.topic_continuation_independent
    ):
        return False
    if profile.topic_continuation_same_x:
        if abs(line.x - heading.line.x) > 12:
            return False
    elif line.x <= heading.line.x + 2:
        return False
    if profile.topic_continuation_independent:
        # Independent means "not at the same x", not "after the body started".
        return not seen_body
    if profile.body_x_min > 0 and line.x < profile.body_x_min:
        return not (profile.strict_continuation and seen_body)
    return not seen_body


def _starts_subheading(text: str) -> bool:
    """A lettered row in the contents column opens a new part of the topic.

    Once one appears, the topic's own name is complete. Everything below it
    belongs to that subheading, not to the title.
    """
    return bool(re.match(r"^(?:[A-Z]\.|\([a-z0-9]+\))\s+", text.strip()))


def parse(lines: list[Line], profile: Profile) -> Syllabus:
    """Parse one PDF's lines using its profile. Fail loudly on a bad shape."""
    scope = _scope(lines, profile)
    headings = _bands(scope, profile)
    if not headings:
        raise ParseError(f"{profile.slug}: no topics found after {profile.start_marker!r}")

    topics: list[Topic] = []
    section_indexes: list[int] = []
    section_re = re.compile(profile.section_re)
    consumed_ids: set[int] = set()
    for position, heading in enumerate(headings):
        following = headings[position + 1] if position + 1 < len(headings) else None
        band = [
            line
            for line in scope
            if line is not heading.line
            and id(line) not in heading.consumed
            and _in_band(line, heading, following)
            and (not section_re.match(line.text) or profile.section_lines_can_continue)
        ]
        section_ids = {id(line) for line in band if section_re.match(line.text)}
        name = heading.name
        seen_body = False
        closed = False
        name_page, name_y = heading.line.page, heading.line.y
        continuation: set[int] = set()
        # A wrapped heading sits immediately under the heading, in the heading
        # column. Keep it out of the body.
        for line in band:
            if not _in_continuation_zone(line, heading, profile):
                continue
            if line.x < profile.body_x_min and _starts_subheading(line.text):
                closed = True
                continue
            near = (
                profile.continuation_line_gap is not None
                and not closed
                and line.page == name_page
                and 0 < name_y - line.y <= profile.continuation_line_gap
                and line.x < profile.body_x_min
                and len(line.text.split()) <= 6
                and not line.text.rstrip().endswith((".", ";"))
                and line.text.strip().upper() not in {"CONTENTS", "NOTES"}
            )
            if near:
                name = _clean(f"{name} {line.text}")
                continuation.add(id(line))
                name_y = line.y
                continue
            if _is_continuation(
                line,
                heading,
                profile,
                seen_body=seen_body,
                current_name=name,
                closed=closed,
            ):
                name = _clean(f"{name} {line.text}")
                continuation.add(id(line))
                name_page, name_y = line.page, line.y
            elif profile.body_x_min <= line.x <= profile.body_x_max and id(line) not in section_ids:
                seen_body = True

        name = re.sub(
            r"\s+(?:AND|OF|FOR|TO|IN|ON|WITH|THE)$", "", name, flags=re.IGNORECASE
        ).strip()
        name = _stop_topic_name(name, profile)
        name = _tidy_name(name)
        if len(name) > MAX_NAME_CHARS and ":" in name:
            # "Husbandry of selected crops:- varieties/types, ..." is a heading
            # with its body on the same line. Keep the heading.
            prefix = name.split(":", 1)[0].strip()
            if len(prefix.split()) >= 2 and len(prefix) <= MAX_NAME_CHARS:
                name = prefix
        if not name:
            # The heading's second table cell, on the same row, carries the
            # name: "4. (a)" | "Centralized and non-centralized states:".
            same_row = [
                line
                for line in band
                if line.page == heading.line.page
                and abs(line.y - heading.line.y) <= ROW_TOLERANCE
                and heading.line.x < line.x <= profile.body_x_max
                and id(line) not in section_ids
            ]
            if same_row:
                candidate = _tidy_name(same_row[0].text)
                if candidate and not name_defects(candidate):
                    name = candidate
                    continuation.add(id(same_row[0]))
            if not name:
                # A bare marker is a layout artefact, not a topic.
                continue
        body = [
            line
            for line in band
            if profile.body_x_min <= line.x <= profile.body_x_max
            and id(line) not in continuation
            and id(line) not in section_ids
        ]
        notes = [
            line for line in band if line.x > profile.body_x_max and id(line) not in section_ids
        ]

        pieces = _segment(body, profile)
        if not pieces:
            pieces = _segment(notes, profile)
        if not pieces and profile.allow_single_subtopic:
            # A standalone official heading is its own smallest unit. This
            # repeats an official string, it does not invent one.
            pieces = [name]
        subtopics: list[Subtopic] = []
        seen: set[str] = set()
        for piece in pieces:
            for part in _split_inline(piece):
                text = _tidy_name(part)
                key = text.lower()
                if len(text) < 2 or text.isdigit() or key in seen:
                    continue
                rules = {rule for rule, _ in name_defects(text)}
                if rules & {"too_long", "sentence", "dangling_end", "fragment"}:
                    # A paragraph, a sentence or a half-phrase is not a target.
                    # The topic remains, and the fallback below keeps it
                    # choosable at topic level.
                    continue
                seen.add(key)
                subtopics.append(Subtopic(name=text, order=len(subtopics) + 1))
        if not subtopics and profile.allow_single_subtopic and len(name) <= MAX_NAME_CHARS:
            subtopics.append(Subtopic(name=name, order=1))
        topics.append(Topic(name=name, order=len(topics) + 1, subtopics=subtopics))
        section_indexes.append(heading.index)
        consumed_ids.update(id(line) for line in heading.consumed)
        consumed_ids.update(continuation)

    sections = _section_map(scope, section_re, skip=consumed_ids)
    topic_sections = [sections[index] for index in section_indexes]
    topics = _disambiguate(topics, topic_sections)
    if profile.merge_duplicate_topics:
        topics = _merge_duplicates(topics)
    # A heading the source itself cut before its object ("The Gambia and the")
    # cannot be a target. Dropping it is honest; renaming it would invent one.
    topics = [topic for topic in topics if not _incomplete(topic.name)]
    for position, topic in enumerate(topics, start=1):
        topic.order = position

    syllabus = Syllabus(subject=profile.slug, display=profile.display, topics=topics)
    errors = validate(syllabus, expected_topics=profile.expected_topics)
    if errors:
        raise ParseError(f"{profile.slug}: " + "; ".join(errors))
    return syllabus


#: Table furniture that is not a section heading.
_TABLE_HEADERS = frozenset(
    {"S/NO CONTENTS", "CONTENTS", "NOTES", "S/N AUTHOR", "TITLE", "PUBLISHER"}
)

#: Acronyms a title-cased section label would otherwise mangle.
_ACRONYMS = {"Ecowas": "ECOWAS", "Waec": "WAEC", "Jamb": "JAMB"}

#: Words a heading keeps lower-case unless they start it.
_SMALL_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)


def _smart_title(text: str) -> str:
    """Title-case a heading without shouting or capitalising every "and"."""
    raw = text.split()
    words: list[str] = []
    for position, word in enumerate(raw):
        lowered = word.lower()
        after_colon = position > 0 and raw[position - 1].endswith(":")
        if position > 0 and lowered in _SMALL_WORDS and not after_colon:
            words.append(lowered)
        elif word.isupper():
            words.append(word[:1] + word[1:].lower())
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def _section_label(text: str) -> str:
    """A short, readable name for the section a topic sits in.

    A label is only useful as a qualifier when it names a real section. Table
    headers, exam-paper labels and lettered subsections are not sections; they
    return an empty label, and the duplicate rule decides what happens next.
    """
    label = re.sub(r"\s+", " ", text).strip()
    if not label:
        return ""
    upper = label.upper()
    if upper in _TABLE_HEADERS or upper.startswith("S/NO "):
        return ""
    # "B. Privatisation" is a subsection of the topic above it.
    if re.match(r"^[A-Z]\.\s+", label):
        return ""
    for prefix in (
        "Regional geography of ",
        "Elements of practical and ",
        "Aspects of ",
    ):
        if label.lower().startswith(prefix.lower()):
            label = label[len(prefix) :].strip()
            break
    # "Paper 1" says which paper, not which part of the syllabus.
    if re.match(r"^Paper\s+\d+\b", label, re.IGNORECASE):
        return ""
    label = label.rstrip(":").strip()
    if not label:
        return ""
    label = _smart_title(label)
    for wrong, right in _ACRONYMS.items():
        label = label.replace(wrong, right)
    return label


def _section_map(
    scope: list[Line], section_re: re.Pattern[str], *, skip: set[int] | None = None
) -> list[str]:
    """The section in force at each line, with multi-line headings joined.

    ``skip`` holds lines already consumed as a topic heading's continuation.
    A wrapped heading often looks like a section ("BUSINESS", "MANAGEMENT");
    letting it become a section would qualify an unrelated topic with it.
    """
    skip = skip or set()
    labels: list[str] = []
    block: list[Line] = []
    current = ""
    for line in scope:
        if id(line) not in skip and section_re.match(line.text):
            # A wrapped heading keeps its x. A new x is a new heading, even
            # when no body line sits between the two.
            if block and abs(line.x - block[-1].x) > 2.0:
                current = _section_label(" ".join(item.text for item in block))
                block = []
            block.append(line)
        elif block:
            current = _section_label(" ".join(item.text for item in block))
            block = []
        labels.append(current)
    return labels


def _disambiguate(topics: list[Topic], sections: list[str]) -> list[Topic]:
    """Qualify duplicate topic names with the section that separates them.

    "Mining" appears once in each regional syllabus. The id is unique either
    way, but a model choosing an id by name cannot tell them apart. The section
    heading is official text, so the qualifier does not invent a name.
    """
    groups: dict[str, list[int]] = {}
    for index, topic in enumerate(topics):
        groups.setdefault(topic.name.casefold(), []).append(index)
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        labels = [sections[index] for index in indexes]
        nonempty = [label for label in labels if label]
        if not nonempty:
            continue
        if len(set(nonempty)) == 1 and len(nonempty) == len(labels):
            # The same section label on every duplicate cannot tell them apart.
            continue
        for index, label in zip(indexes, labels, strict=True):
            if not label:
                continue
            candidate = f"{topics[index].name} ({label})"
            if len(candidate) <= MAX_NAME_CHARS:
                topics[index].name = candidate
    return topics


def _merge_duplicates(topics: list[Topic]) -> list[Topic]:
    """A repeated page heading continues a topic; it does not start a new one."""
    merged: list[Topic] = []
    seen: dict[str, Topic] = {}
    for topic in topics:
        key = _clean(topic.name).lower()
        target = seen.get(key)
        if target is None:
            seen[key] = topic
            merged.append(topic)
            continue
        names = {sub.name.lower() for sub in target.subtopics}
        for subtopic in topic.subtopics:
            if subtopic.name.lower() not in names:
                target.subtopics.append(subtopic)
                names.add(subtopic.name.lower())
    for position, topic in enumerate(merged, start=1):
        topic.order = position
        for sub_position, subtopic in enumerate(topic.subtopics, start=1):
            subtopic.order = sub_position
    return merged


def _in_continuation_zone(line: Line, heading: _Heading, profile: Profile) -> bool:
    """Only rows at or below the heading can continue its name."""
    if line.page < heading.line.page:
        return False
    if line.page > heading.line.page:
        return True
    return line.y <= heading.line.y + ROW_TOLERANCE


def validate(syllabus: Syllabus, expected_topics: int | None = None) -> list[str]:
    errors: list[str] = []
    if not syllabus.topics:
        errors.append("no topics")
    if expected_topics is not None and len(syllabus.topics) != expected_topics:
        errors.append(f"expected {expected_topics} topics, found {len(syllabus.topics)}")
    for topic in syllabus.topics:
        if not topic.name:
            errors.append(f"topic {topic.order} has no name")
        if not topic.subtopics:
            errors.append(f"topic {topic.order} ({topic.name!r}) has no subtopics")
        for subtopic in topic.subtopics:
            if not subtopic.name:
                errors.append(f"topic {topic.order} has an empty subtopic")
    return errors


__all__ = ["ParseError", "parse", "validate"]
