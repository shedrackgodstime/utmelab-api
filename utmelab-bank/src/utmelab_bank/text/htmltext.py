"""HTML to text, once.

``clean_inline`` was pasted between the JAMB harvester and the WAEC harvester
with the annotations and the docstring removed, and the two copies of
``unescape_segment`` had already diverged: one protected ampersands with a
sentinel before unescaping, the other replaced every ampersand with a marker and
restored it afterwards. They decoded ``&amp;lt;`` differently, so the same
question could end up with different text depending on which harvester saw it.

There is one copy now.
"""

from __future__ import annotations

import html
import json
import re
from typing import Final

from utmelab_bank.model.richtext import Mark

__all__ = [
    "has_numbered_gap",
    "mentions_cloze",
    "mentions_figure",
    "visible_lines",
    "clean_inline",
    "strip_tags",
    "unescape_once",
    "promises_stimulus",
    "FIGURE_HINT",
    "CLOZE_HINT",
    "NUMBERED_GAP",
    "PROMISED_STIMULUS",
    "INLINE_TAGS",
]

#: The words that mean the stem is about a figure it must ship with.
#:
#: This is the table from the archive's ``quarantine.rs``, which is the rule of
#: record, and its shape matters. ``figure`` and ``table`` are exact words
#: because both are ordinary English and "based on the table of contents" is not
#: a diagram. ``diagram``, ``graph`` and ``sketch`` take a plural. ``illustrat``
#: is a stem so it catches illustrated and illustration. ``shown`` is exact.
#:
#: An earlier version of this file used a bag of collocations instead
#: ("as shown in the diagram", "the graph above") and measurably missed rows the
#: proven rule catches: a bare "sketch", a bare "shown", "the illustration
#: below", "the organ shown in the figure". A figure hint that slips through
#: ships a question whose candidate sees no figure.
_HINTS: Final[tuple[tuple[str, bool, bool], ...]] = (
    ("diagram", True, False),      # (word, plural allowed, prefix match)
    ("figure", False, False),
    ("graph", True, False),
    ("illustrat", False, True),
    ("shown", False, False),
    ("sketch", True, False),
    ("table", False, False),
)

#: Built once at import, so the cost is not paid per row.
_HINT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(" + "|".join(
        (rf"{word}(?:e?s)?" if plural else word) if not prefix else rf"{word}\w*"
        for word, plural, prefix in _HINTS
    ) + r")\b",
    re.IGNORECASE,
)

#: One exclusion the archive does not have. "Based on the table of contents"
#: fires the bare word ``table``, and the archive's rule is deliberately a word
#: scan, so it would refuse that row. Refusing a real row is the expensive
#: direction, and this phrase has no diagram in it, so it is carved out here and
#: noted as an addition rather than a port.
_FIGURE_EXCLUSIONS: Final[re.Pattern[str]] = re.compile(
    r"\btable\s+of\s+contents\b|\bcontents\s+table\b",
    re.IGNORECASE,
)

#: Multiword phrases the harvester also honoured. Kept as well, because a
#: false positive costs one row and a false negative ships a broken question.
_EXTRA_FIGURE_PHRASES: Final[re.Pattern[str]] = re.compile(
    r"(stave\s+(?:above|below)"
    r"|reaction\s+scheme"
    r"|(above|below)\s+(?:is|are)\s+(?:the|a|an)?\s*(?:figure|diagram|chart|graph|image)"
    r"|photograph)",
    re.IGNORECASE,
)

#: A blank that cannot be answered without its stimulus. The archive's version
#: is about the instruction, not the word "passage": it catches "fill the gap
#: labelled 6" and deliberately does not fire on "read the passage", which is a
#: perfectly answerable question once the passage travels with it.
CLOZE_HINT: Final[re.Pattern[str]] = re.compile(
    r"\b(?:fill|complete|supply|choose|replace|write)[a-z ]{0,14}"
    r"\b(?:gap|blank|space|passage)\b",
    re.IGNORECASE,
)

#: A numbered gap names something that is absent, so it is a stimulus promise in
#: its own right regardless of the wording around it.
NUMBERED_GAP: Final[re.Pattern[str]] = re.compile(
    r"\b(?:gap|blank|space|passage)\b[^.]{0,20}?\b(?:labelled|labeled|numbered|no\.?)\s*\d+"
    r"|\b\d+\s*(?:gap|blank)\b",
    re.IGNORECASE,
)

#: Phrases that promise a stimulus. The harvester and the passage recovery tool
#: each carried their own ten-string tuple and the pipeline carried a third
#: pattern list, all disagreeing about whether "information below" counts.
#:
#: A figure is deliberately absent. "the diagram below" is handled by the image
#: check, because a figure travels as an image mark and needs no passage, and
#: listing it here made every question carrying a figure fail the stimulus rule
#: for no reason.
PROMISED_STIMULUS: Final[re.Pattern[str]] = re.compile(
    r"(\bthe\s+(information|data|table|figures?\s+below|values?\s+below|"
    r"extract|passage|text|schedule|results?)\b"
    r"|\bfrom\s+the\s+(table|data|figures?)\b"
    r"|\bthe\s+table\s+below\b"
    r"|\bin\s+the\s+table\s+(above|below)\b"
    r"|\bthe\s+study\s+of\b"
    r"|\baccording\s+to\s+the\s+(passage|text|table)\b)",
    re.IGNORECASE,
)

#: Tags that carry meaning we keep as a mark. Everything else is dropped.
#:
#: The subscript, superscript and strikethrough kinds are not decorative. A
#: chemistry stem written ``H<sub>2</sub>O`` and a physics stem written
#: ``x<sup>2</sup>`` are unreadable without them, and the importer on the other
#: side already accepts all three, so a bank can hold marks this model could not
#: represent.
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

#: Tags that are a line break. They are not marks, but they are not nothing
#: either: dropping one with no space glues two words together, which is how
#: "line oneline two" reached the bank.
_BREAK_TAGS: Final[frozenset[str]] = frozenset({"br"})

_SCRIPT_STYLE: Final[re.Pattern[str]] = re.compile(
    r"(?s)<script.*?</script>|<style.*?</style>"
)

#: The hydration markers a Nuxt template is full of. Not matched by a tag regex,
#: so they have to be named.
_COMMENT: Final[re.Pattern[str]] = re.compile(r"(?s)<!--.*?-->")

#: Any tag at all, comments aside.
_ANY_TAG: Final[re.Pattern[str]] = re.compile(r"(?s)<[^>]*>")

_BLOCK_BREAK: Final[re.Pattern[str]] = re.compile(
    r"</(p|div|li|tr|h[1-6]|blockquote|table|section|article)>|<br\s*/?>",
    re.IGNORECASE,
)

_TAG: Final[re.Pattern[str]] = re.compile(r"<\s*(/?)\s*([a-zA-Z0-9]+)[^>]*>")

#: Whitespace inside one text run collapses to a single space.
_WS: Final[re.Pattern[str]] = re.compile(r"\s+")
_ATTR: Final[re.Pattern[str]] = re.compile(r"""([a-zA-Z-]+)\s*=\s*["']([^"']*)["']""")

#: Page furniture that is never part of a question.
_NOISE: Final[tuple[str, ...]] = (
    "mySchool.ng",
    "Advertisement",
    "Click here",
    "Sign up",
    "Log in",
    "©",
    "Copyright",
)


def mentions_figure(text: str) -> bool:
    """Whether the text talks about a figure it does not carry."""
    plain = strip_tags(text)
    if _FIGURE_EXCLUSIONS.search(plain):
        return False
    return bool(_HINT_RE.search(plain) or _EXTRA_FIGURE_PHRASES.search(plain))


def has_numbered_gap(text: str) -> bool:
    """Whether the stem names a gap that is not there.

    Separate from :func:`mentions_cloze` because this one is a stimulus promise
    in its own right: "the gap labelled 6" names a specific missing thing, so it
    is refused even when the surrounding wording looks answerable.
    """
    return bool(NUMBERED_GAP.search(strip_tags(text)))


def mentions_cloze(text: str) -> bool:
    """Whether the stem asks the candidate to fill something in."""
    return bool(CLOZE_HINT.search(strip_tags(text)))


def promises_stimulus(text: str) -> bool:
    """Whether the stem points at a stimulus that has to travel with it.

    The rule the harvester applied is refuse only when the passage is genuinely
    absent, which is different from refusing every cloze. Two harvesters
    disagreed and one banned all cloze stems outright.
    """
    return bool(PROMISED_STIMULUS.search(strip_tags(text)))


def strip_tags(text: str) -> str:
    """Text with markup removed and entities decoded, whitespace collapsed."""
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", text))).strip()


def unescape_once(text: str) -> str:
    """Decode entities exactly one level.

    The WAEC API returns already-decoded names, so running its copy of the
    entity table turned ``&amp;`` into nothing at all. Decoding once is the only
    rule that works for both sources.
    """
    return html.unescape(text)


def visible_lines(markup: str) -> list[str]:
    """The lines of a page that a person would read as content.

    Ported from ``tools/harvest.py``, and three details of it are load-bearing:

    * **Script and style bodies go first.** The page's own css contains text
      that reads like a heading, and a stylesheet is not content.
    * **Comments go.** The page is a Nuxt template, so its body is full of
      ``<!---->`` hydration markers. They are not tags as far as a tag regex is
      concerned, so a version that matches ``<[a-z]...>`` keeps them as literal
      text and the passage reader then anchors on one.
    * **Every remaining tag becomes a newline, not a space.** A tag that held a
      block boundary is a line break; a tag that held a word boundary is
      handled by the block regex above.
    """
    stripped = _SCRIPT_STYLE.sub(" ", markup)
    stripped = _COMMENT.sub(" ", stripped)
    broken = _BLOCK_BREAK.sub("\n", stripped)
    broken = _ANY_TAG.sub("\n", broken)

    out: list[str] = []
    for line in broken.split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", html.unescape(line)).strip()
        if len(cleaned) < 2:
            continue
        if any(noise in cleaned for noise in _NOISE):
            continue
        out.append(cleaned)
    return out


def clean_inline(markup: str) -> tuple[str, list[Mark]]:
    """Flatten inline html into text plus marks.

    **Entities are decoded per text run, before anything is measured.** This is
    the part that is easy to get wrong and that the archive worked out first.
    ``&ldquo;`` is nine characters in the source and one in the output, so an
    implementation that measures on the raw string and unescapes at the end
    computes every offset after it too far. Measured on the real site, whose
    ``<h1>`` pads the stem with ``&nbsp;`` paragraphs:

        '&ldquo;cogent&rdquo; means <u>persuasive</u> in law.'
            raw measurement   the underline is dropped entirely
            per-run           underline at 15, length 10, on "persuasive"

    The archive's ``harvest.py`` and ``harvest_waec.py`` each carried their own
    copy of this and each had drifted: one protected ampersands with a sentinel
    before unescaping, the other replaced every ampersand with a marker and
    restored it afterwards, so the same question decoded differently depending
    on which harvester saw it. One copy, decoded once per run, both fixed.
    """
    out: list[str] = []
    marks: list[Mark] = []
    #: Tag name to the output length at the point it opened.
    open_at: dict[str, int] = {}
    position = 0

    def push(run: str) -> None:
        """Append one run of source text, decoded and measured as it lands."""
        decoded = _WS.sub(" ", unescape_once(run))
        if decoded:
            out.append(decoded)

    for match in _TAG.finditer(markup):
        push(markup[position : match.start()])
        position = match.end()

        closing = match.group(1) == "/"
        tag = match.group(2).lower()

        if tag in _BREAK_TAGS:
            # Checked before the inline filter, because ``br`` is not a mark and
            # would otherwise be dropped as an unknown tag, gluing the words on
            # either side together.
            push(" ")
            continue

        if tag not in INLINE_TAGS:
            continue

        if closing:
            started = open_at.pop(tag, None)
            kind = INLINE_TAGS[tag]
            span = len("".join(out)) - started if started is not None else 0
            # An unclosed mark runs to the end of the text, never past it.
            if kind != "image" and started is not None and span >= 0:
                marks.append(Mark(kind=kind, start=started, len=span))  # type: ignore[arg-type]
            continue

        if tag == "img":
            attrs = dict(_ATTR.findall(match.group(0)))
            url = attrs.get("src", "")
            if url:
                marks.append(
                    Mark(
                        kind="image",
                        start=len("".join(out)),
                        len=0,
                        url=url,
                        alt=attrs.get("alt") or None,
                    )
                )
            continue

        open_at.setdefault(tag, len("".join(out)))

    push(markup[position:])
    for tag, started in list(open_at.items()):
        kind = INLINE_TAGS[tag]
        marks.append(Mark(kind=kind, start=started, len=len("".join(out)) - started))  # type: ignore[arg-type]
    marks.sort(key=lambda mark: (mark.start, mark.len))

    return _trim("".join(out), marks)


def _trim(raw: str, marks: list[Mark]) -> tuple[str, list[Mark]]:
    """Trim the text and slide every mark along with it.

    A mark computed against the untrimmed string points too far right once the
    leading whitespace goes, and an image mark that sat after the stem must be
    pulled back to the end rather than dropped, because that is where a figure
    below the stem belongs.
    """
    stripped = raw.strip()
    lead = len(raw) - len(raw.lstrip())
    shifted = [
        mark.model_copy(update={"start": max(0, mark.start - lead), "len": mark.len})
        for mark in marks
    ]
    return stripped, _renumber(stripped, shifted)


def _renumber(text: str, marks: list[Mark]) -> list[Mark]:
    """Repair marks after the text was trimmed.

    Unescaping can shorten the text and trimming certainly does, so a mark
    computed against the untrimmed string can end past the end.

    An image mark is a location rather than a span, so one that overshoots is
    pulled back to the end rather than dropped: a figure below the stem is at
    the end of the stem, and dropping the mark is how a question carrying a
    perfectly good diagram ended up looking as though it had none.

    A text mark that overshoots is dropped, because clamping it would underline
    the wrong words, which is worse than having no underline at all.
    """
    limit = len(text)
    kept: list[Mark] = []
    for mark in marks:
        if mark.kind == "image":
            kept.append(mark.model_copy(update={"start": min(mark.start, limit)}))
            continue
        if mark.start < limit and mark.end <= limit:
            kept.append(mark)
    return kept
