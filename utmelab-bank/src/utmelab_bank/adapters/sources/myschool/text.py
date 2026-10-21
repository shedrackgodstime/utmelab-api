"""Inline HTML into text plus marks, once.

The site's question markup is small but not plain: an underline in a stem, a
subscript in a chemistry formula, an ``<img>`` for a diagram. This module
turns that markup into the production rich-text shape.

Entities are decoded per text run, before anything is measured. ``&ldquo;`` is
nine characters in the source and one in the output, so measuring the raw
string and unescaping at the end computes every later offset too far right.

The production model refuses partially overlapping marks. HTML happily nests
them (``<b>ab<u>c</u></b>``), so the builder keeps the first mark of an
overlap and drops the rest rather than refusing the whole row for a cosmetic
style.
"""

from __future__ import annotations

import html
import re
from typing import Final

from utmelab_bank.domain.enums import ImagePosition, InlineKind
from utmelab_bank.domain.models import Inline

__all__ = ["clean_inline"]

#: Tags that carry a mark we keep. Everything else is dropped.
INLINE_TAGS: Final[dict[str, str]] = {
    "u": "underline",
    "strong": "bold",
    "b": "bold",
    "em": "italic",
    "i": "italic",
    "s": "strike",
    "strike": "strike",
    "del": "strike",
    "sub": "subscript",
    "sup": "superscript",
    "img": "image",
}

#: A break is not a mark, but it is not nothing either: dropping it with no
#: space glues the words on either side together.
_BREAK_TAGS: Final[frozenset[str]] = frozenset({"br"})

_TAG: Final[re.Pattern[str]] = re.compile(r"<\s*(/?)\s*([a-zA-Z0-9]+)[^>]*>")
_WS: Final[re.Pattern[str]] = re.compile(r"\s+")
_ATTR: Final[re.Pattern[str]] = re.compile(r"""([a-zA-Z-]+)\s*=\s*["']([^"']*)["']""")


def clean_inline(markup: str) -> tuple[str, tuple[Inline, ...]]:
    """Flatten inline markup into text plus marks.

    The returned offsets are in Unicode characters of the returned text, which
    is the production contract. Image marks are zero-length anchors and carry
    their position because the same figure above the stem is not the same
    document as the same figure below it.
    """
    out: list[str] = []
    marks: list[Inline] = []
    open_at: dict[str, int] = {}
    size = 0
    position = 0

    def push(run: str) -> None:
        nonlocal size
        decoded = _WS.sub(" ", html.unescape(run))
        if not decoded:
            return
        # Runs meet at tag boundaries. Without this, ``<b>Look </b> here``
        # keeps both spaces and the stem reads "Look  here".
        if out and out[-1].endswith(" ") and decoded.startswith(" "):
            decoded = decoded[1:]
        if decoded:
            out.append(decoded)
            size += len(decoded)

    for match in _TAG.finditer(markup):
        push(markup[position : match.start()])
        position = match.end()

        closing = match.group(1) == "/"
        tag = match.group(2).lower()

        if tag in _BREAK_TAGS:
            push(" ")
            continue

        if tag not in INLINE_TAGS:
            continue

        if closing:
            started = open_at.pop(tag, None)
            kind = INLINE_TAGS[tag]
            if kind != "image" and started is not None:
                span = size - started
                if span > 0:
                    marks.append(_text_mark(kind, started, span))
            continue

        if tag == "img":
            attrs = dict(_ATTR.findall(match.group(0)))
            url = html.unescape(attrs.get("src", "")).strip()
            alt = html.unescape(attrs.get("alt", "")).strip()
            if url:
                marks.append(
                    Inline(
                        kind=InlineKind.IMAGE,
                        start=size,
                        len=0,
                        url=url,
                        position=ImagePosition.BELOW,
                        alt=alt or None,
                    )
                )
            continue

        open_at.setdefault(tag, size)

    push(markup[position:])
    for tag, started in list(open_at.items()):
        span = size - started
        if span > 0:
            marks.append(_text_mark(INLINE_TAGS[tag], started, span))

    marks.sort(key=lambda mark: (mark.start, mark.len))
    text, trimmed = _trim("".join(out), marks)
    return text, _without_partial_overlaps(trimmed)


def _text_mark(kind: str, start: int, length: int) -> Inline:
    return Inline(kind=InlineKind(kind), start=start, len=length)


def _trim(raw: str, marks: list[Inline]) -> tuple[str, list[Inline]]:
    """Trim the text and slide every mark along with it.

    A mark computed against the untrimmed string points too far right once
    leading whitespace goes. An image that sat after the stem is pulled back
    to the end rather than dropped, because that is where a figure below the
    stem belongs. A text mark that overshoots is dropped, because clamping it
    would underline the wrong words.
    """
    stripped = raw.strip()
    lead = len(raw) - len(raw.lstrip())
    limit = len(stripped)
    shifted: list[Inline] = []
    for mark in marks:
        if mark.kind is InlineKind.IMAGE:
            shifted.append(mark.model_copy(update={"start": min(max(0, mark.start - lead), limit)}))
            continue
        start = max(0, mark.start - lead)
        end = mark.start + mark.len - lead
        if start < limit and end <= limit and mark.len > 0:
            shifted.append(
                mark.model_copy(update={"start": start, "len": min(mark.len, limit - start)})
            )
    return stripped, shifted


def _without_partial_overlaps(marks: list[Inline]) -> tuple[Inline, ...]:
    """Keep a valid set when HTML nested marks of different lengths.

    The production model allows identical ranges and rejects a partial
    overlap, so the first mark in (start, len) order wins. Image anchors have
    zero length and never overlap anything.
    """
    kept: list[Inline] = []
    for mark in sorted(marks, key=lambda item: (item.start, item.len)):
        if mark.kind is InlineKind.IMAGE:
            kept.append(mark)
            continue
        if any(
            other.kind is not InlineKind.IMAGE
            and not (mark.start == other.start and mark.len == other.len)
            and other.start < mark.start + mark.len
            and mark.start < other.start + other.len
            for other in kept
        ):
            continue
        kept.append(mark)
    return tuple(kept)
