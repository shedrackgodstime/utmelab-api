"""Read a syllabus PDF as positioned lines.

The WAEC PDFs are tables: a contents column and a notes column, or a single
column with hanging indents. Flat text throws away the column and the indent,
which is the only thing that separates a topic from its body. These lines keep
both.

pypdf splits words at font changes ("marg inal"); pdfminer groups characters by
position and does not, so it is the extractor here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextContainer, LTTextLine

#: Two elements within this vertical distance are on the same printed line.
LINE_TOLERANCE = 3.5

#: A marker and its name are close. Two table columns are not.
MERGE_GAP = 60.0

#: A printed page number, with or without the "Page" label. These sit inside the
#: body column on some WAEC PDFs, so position alone does not remove them.
_PAGE_NUMBER = re.compile(
    r"^(?:\d{1,4}|Page\s+\d{1,4}|\d{1,4}\s*\|\s*P\s*a\s*g\s*e|P\s*a\s*g\s*e\s*\|\s*\d{1,4})$",
    re.IGNORECASE,
)


def _is_page_number(text: str, x: float) -> bool:
    """A bare number is a page number only in the margin, not a topic number."""
    if not _PAGE_NUMBER.match(text):
        return False
    return "|" in text or text.lower().startswith("page") or x > 300


@dataclass(frozen=True, slots=True)
class Line:
    """One printed line, with the x of its first element."""

    page: int
    x: float
    y: float
    text: str
    size: float = 0.0


def _tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Some PDFs print "1. 0" instead of "1.0". The decimal is the topic number,
    # not two tokens, so close the gap before any profile regex sees it.
    text = re.sub(r"^(\d+)\.\s+(\d+)", r"\1.\2", text)
    # "( a )" is a marker, not three tokens.
    text = re.sub(r"\(\s*([a-z])\s*\)", r"(\1)", text)
    text = re.sub(r"\(\s*([ivx]+)\s*\)", r"(\1)", text)
    # A parenthesised marker glued to its text reads badly and hides the
    # marker from the profile regexes. Decimal topic numbers are left alone:
    # "1.0" must not become "1. 0" again. This is not anchored: a table row
    # often prints two markers on one line ("(i) Hospitality (ii) Catering").
    return re.sub(r"(\([a-z]+\)|\([ivx]+\))(?=\w)", r"\1 ", text)


def _merge(raw: list[tuple[float, float, str, float]]) -> list[Line]:
    """Join the marker and the name that sit on the same printed line."""
    raw = sorted(raw, key=lambda item: (-item[1], item[0]))
    merged: list[tuple[float, float, str, float]] = []
    for x, y, text, size in raw:
        if merged and abs(merged[-1][1] - y) <= LINE_TOLERANCE and x - merged[-1][0] < MERGE_GAP:
            prev_x, prev_y, prev_text, prev_size = merged[-1]
            merged[-1] = (prev_x, prev_y, f"{prev_text} {text}", max(prev_size, size))
        else:
            merged.append((x, y, text, size))
    return [
        Line(page=0, x=x, y=y, text=_tidy(text), size=size)
        for x, y, text, size in merged
        if text.strip()
    ]


def read_lines(path: Path) -> list[Line]:
    """Every non-empty printed line in the document, in reading order."""
    laparams = LAParams(char_margin=2.0, line_margin=0.3)
    lines: list[Line] = []
    for page_number, page in enumerate(extract_pages(str(path), laparams=laparams), start=1):
        raw: list[tuple[float, float, str, float]] = []
        for element in page:
            if not isinstance(element, LTTextContainer):
                continue
            for line in element:
                if not isinstance(line, LTTextLine):
                    continue
                text = line.get_text().strip()
                if not text:
                    continue
                x0, y0, _x1, _y1 = line.bbox
                if _is_page_number(text, float(x0)):
                    continue
                size = max((char.size for char in line if hasattr(char, "size")), default=0.0)
                raw.append((float(x0), float(y0), text, float(size)))
        for line in _merge(raw):
            lines.append(Line(page=page_number, x=line.x, y=line.y, text=line.text, size=line.size))
    return lines


def text_of(lines: list[Line]) -> str:
    return " ".join(line.text for line in lines)


def normalise(text: str) -> str:
    """The comparison form: no case, no spaces, no punctuation."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


__all__ = ["Line", "normalise", "read_lines", "text_of"]
