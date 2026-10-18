"""RichText and the marks that hang off it.

A stem is text plus a list of marks, and a mark is a byte range plus a kind.
That is the whole shape, and it is the shape the API reads and the shape a
model must produce. Two rules hold everywhere:

- Offsets are byte ranges into the text they annotate, never into a normalised
  copy of it. A model that counts characters after lowercasing produces marks
  that point at the wrong words.
- Every offset is validated on the way in, so a bad range is caught at the
  boundary rather than at read time in production.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from utmelab_bank.model.base import BankModel

__all__ = [
    "Mark",
    "MarkKind",
    "Option",
    "RichText",
    "mark_key",
    "snap_offsets",
]

#: The kinds the bank can hold. Subscript, superscript and strikethrough are
#: here because the importer on the API side already accepts all three
#: (``model.rs`` InlineKind), so a bank row can carry them. A model that cannot
#: represent a mark a bank row holds is a model that cannot read the bank.
MarkKind = Literal[
    "underline",
    "image",
    "bold",
    "italic",
    "strike",
    "subscript",
    "superscript",
]


def _valid_len(value: int) -> int:
    """Length sanity for a mark.

    Zero is allowed. Every image mark in the committed bank carries ``len: 0``,
    because the importer and the harvester both wrote ``"len": 0`` for a figure,
    and rejecting that makes the package unable to read a single question that
    has a diagram. Text marks still must cover something, so that is checked in
    :meth:`RichText._check_ranges` where the kind is known.
    """
    if value < 0:
        raise ValueError("a mark cannot have a negative length")
    if value > 4000:
        raise ValueError("a mark longer than 4000 characters is not an underline")
    return value


def _valid_start(value: int) -> int:
    if value < 0:
        raise ValueError("a mark cannot start before the text")
    return value


class Mark(BankModel):
    """One annotated range. ``start`` and ``len`` index the owning text."""

    kind: MarkKind
    start: Annotated[int, AfterValidator(_valid_start)]
    len: Annotated[int, AfterValidator(_valid_len)]
    url: str | None = None
    alt: str | None = None
    position: Literal["above", "below", "inline"] = "above"

    @model_validator(mode="after")
    def _image_needs_a_url(self) -> Mark:
        if self.kind == "image" and not self.url:
            raise ValueError("an image mark must carry the url it points at")
        return self

    @property
    def end(self) -> int:
        return self.start + self.len


def mark_key(mark: Mark | dict[str, object]) -> str:
    """The stable string form of a mark, used by the content hash.

    An image mark folds in its url, position and alt text because two otherwise
    identical stems pointing at different figures are different questions. This
    format is part of the contract with the API, so it does not change without
    a content hash version bump.
    """
    data = mark if isinstance(mark, dict) else mark.model_dump()
    kind = str(data.get("kind", ""))
    if kind == "image":
        inner = ":".join(
            [
                str(data.get("url", "")),
                str(data.get("position", "above")),
                str(data.get("alt") or ""),
            ]
        )
        kind = f"image:{inner}"
    return f"{data.get('start', 0)},{data.get('len', 0)},{kind}"


class RichText(BankModel):
    """Text plus its marks. The unit every explanation part and every stem uses."""

    text: str
    inline: list[Mark] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_ranges(self) -> RichText:
        """Reject a mark that points outside the text it annotates.

        This is the one validation that cannot be skipped, because an
        out-of-range mark is invisible at write time and a crash at read time in
        the API.

        An image mark is a location, not a span, so it is allowed to sit exactly
        at the end of the text: that is where a figure below the stem goes, and
        rejecting it is how a question carrying a perfectly good diagram lost
        its mark.

        Underlines are additionally checked for overlap, sorted by position, so
        two of them never fight over the same span.
        """
        limit = len(self.text)
        for mark in self.inline:
            if mark.kind == "image":
                # An image mark is a location, not a span. It may sit at the end
                # of the text, which is where a figure below the stem goes, and
                # it may carry a length of zero, which is what the committed
                # bank stores.
                if mark.start > limit:
                    raise ValueError(
                        f"image mark sits at {mark.start} but the text is {limit} characters"
                    )
                continue
            if mark.len < 1:
                raise ValueError("a text mark must cover at least one character")
            if mark.end > limit:
                raise ValueError(
                    f"mark covers {mark.start}..{mark.end} but the text is {limit} characters"
                )
        spans = sorted((m.start, m.end) for m in self.inline if m.kind == "underline")
        for (_a_start, a_end), (b_start, _b_end) in zip(spans, spans[1:], strict=False):
            if b_start < a_end:
                raise ValueError(f"underline marks overlap at {b_start}")
        return self

    @property
    def plain(self) -> str:
        return self.text


class Option(BankModel):
    """One choice. The label is the key letter the answer points at."""

    id: str = Field(min_length=1, max_length=8)
    text: RichText


def snap_offsets(
    text: str,
    marks: list[Mark],
    *,
    finder: str | None = None,
) -> list[Mark]:
    """Nudge model-produced offsets onto real word boundaries.

    Models count spaces inconsistently and occasionally return a range one
    character off. Rather than reject the row and lose the content, we slide
    each mark to the nearest whitespace boundary, and drop the ones that cannot
    be repaired. ``finder`` is the phrase the model claims it marked; when it is
    given, we prefer the real occurrence over the model's arithmetic.
    """
    if not text:
        return []
    limit = len(text)
    repaired: list[Mark] = []
    for orig in marks:
        mark = orig
        if finder:
            found = text.find(finder)
            if found >= 0:
                mark = mark.model_copy(update={"start": found, "len": len(finder)})
        start = max(0, min(mark.start, max(0, limit - 1)))
        end = min(limit, mark.end)
        if end <= start:
            continue
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        while end < limit and not text[end].isspace():
            end += 1
        if end <= start:
            continue
        repaired.append(mark.model_copy(update={"start": start, "len": end - start}))
    return [m for m in repaired if m.end <= limit]
