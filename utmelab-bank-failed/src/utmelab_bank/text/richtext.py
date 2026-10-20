"""Building and repairing RichText.

Marks are byte ranges into text, and four separate places used to build them:
the harvesters, the two auto-verify scripts, and the pipeline's snapping helper.
Each had its own idea of what a mark was, so an underline produced by tagging and
one produced by review were not comparable.

``join_rich`` is the only way to combine two pieces of RichText, ``snap`` is the
only repair, and ``clean_blocks`` is the only way to build a passage.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from typing import Any

from utmelab_bank.model.richtext import Mark, RichText, snap_offsets

__all__ = [
    "clean_blocks",
    "from_json",
    "join_rich",
    "merge_words",
    "offset_of",
    "rt",
    "rt_json",
    "snap",
    "unescape_segment",
]

_AMP_SENTINEL = "\x00AMP\x00"


def rt(text: str, marks: Sequence[Mark] | None = None) -> tuple[str, str]:
    """Build the two strings a question row stores: the text and its marks.

    Returns json rather than a model so a harvester can call it while building a
    payload, without pulling the model validators into a scraping hot path. The
    model layer validates when a payload becomes a row.
    """
    payload = [m.model_dump() if isinstance(m, Mark) else dict(m) for m in (marks or [])]
    return text, json.dumps(payload, separators=(",", ":"))


def rt_json(marks: Sequence[Mark | dict[str, Any]]) -> str:
    """Just the marks half, for a column that already has the text."""
    payload = [m.model_dump() if isinstance(m, Mark) else dict(m) for m in marks]
    return json.dumps(payload, separators=(",", ":"))


def from_json(text: str, marks_json: str | None) -> RichText:
    """Rebuild a :class:`RichText` from a row's two columns."""
    if not marks_json:
        return RichText(text=text)
    try:
        raw = json.loads(marks_json)
    except (TypeError, ValueError):
        return RichText(text=text)
    return RichText(text=text, inline=[Mark.model_validate(mark) for mark in raw])


def offset_of(text: str, phrase: str) -> int | None:
    """Where a phrase starts, or ``None`` when it is not in the text.

    Used to prefer a model's stated phrase over its arithmetic, which is the
    difference between an underline on the right words and an underline one
    character off.
    """
    found = text.find(phrase)
    return found if found >= 0 else None


def snap(text: str, marks: Sequence[Mark], finder: str | None = None) -> list[Mark]:
    """Repair model-produced marks. Delegates to the model layer's rule."""
    return snap_offsets(text, list(marks), finder=finder)


def join_rich(parts: Sequence[RichText], separator: str = " ") -> RichText:
    """Join RichText fragments into one, shifting every mark along.

    This is the function whose absence is why a passage could never carry an
    emphasis mark. Joining the *texts* of two fragments and concatenating their
    marks lists is how you get a mark that points at the wrong words, and the
    previous version of this module could only join strings, so every call site
    passed one element or a list of bare text.

    Empty parts are skipped rather than emitting a separator, so a blank
    paragraph in the middle of a stem does not leave a double space.
    """
    texts: list[str] = []
    marks: list[Mark] = []
    position = 0

    for part in parts:
        body = part.text
        if not body:
            continue
        if texts:
            texts.append(separator)
            position += len(separator)
        texts.append(body)
        marks.extend(
            mark.model_copy(update={"start": mark.start + position}) for mark in part.inline
        )
        position += len(body)

    marks.sort(key=lambda mark: (mark.start, mark.len))
    return RichText(text="".join(texts), inline=marks)


def clean_blocks(fragments: Sequence[str]) -> RichText:
    """Block-level fragments into one RichText with blank-line breaks.

    For passage-shaped content only. A passage that is really four paragraphs
    keeps its breaks, and its marks shift with each break. Stems and options
    never come through here: they stay single line via :func:`join_rich` with a
    space.
    """
    from utmelab_bank.text.htmltext import clean_inline

    parts = []
    for fragment in fragments:
        text, marks = clean_inline(fragment)
        parts.append(RichText(text=text, inline=marks))
    return join_rich(parts, "\n\n")


def merge_words(parts: Sequence[str]) -> str:
    """Join bare strings with single spaces and collapse the result.

    Scrapers hand back the same sentence in pieces. Naive concatenation
    produced ``what isthefunction`` in the bank more than once.
    """
    joined = " ".join(part.strip() for part in parts if part and part.strip())
    return " ".join(joined.split())


def unescape_segment(segment: str) -> str:
    """Decode entities in one tag-free run of text, exactly once.

    Enumerating entities by hand is a losing game: this source alone uses
    ``&rsquo;``, ``&deg;``, ``&agrave;``, ``&ordm;``, ``&rarr;``, ``&equiv;``,
    ``&epsilon;`` and the whole accented Latin set. A 139 question payload
    shipped with raw entities because the table was incomplete, and extending it
    by hand simply moved the failure. ``html.unescape`` knows them all.

    The double-escape pass stays explicit and explicit is the point.
    ``&amp;rsquo;`` arrives already escaped once, so unescaping in the wrong
    order leaves ``&rsquo;`` in the bank as visible text. The sentinel protects
    the ampersand through one pass and restores it after, which is what the
    archive settled on after two harvesters each took a different approach and
    decoded the same question differently.
    """
    protected = segment.replace("&amp;amp;", _AMP_SENTINEL)
    decoded = html.unescape(protected)
    return decoded.replace(_AMP_SENTINEL, "&")
