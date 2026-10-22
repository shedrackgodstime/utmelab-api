"""The myschool.ng classroom API.

The site's HTML listing is navigation only; every question is served by
``/api/web/v1/classroom/{subject}``. The API is also better than the page in
the three places that matter: it marks the correct option explicitly, it names
the exam and the year on the row's collection, and it carries the question's
own markup.

This parser is the untrusted edge. It raises ``SourceError`` at the first
thing it cannot trust rather than returning a partial row, because a question
with a guessed key is the one defect a candidate cannot recover from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from utmelab_bank.domain.enums import ImagePosition, InlineKind
from utmelab_bank.domain.models import Inline

from .errors import SourceError
from .subjects import load_map
from .text import clean_inline

__all__ = [
    "API_PAGE_SIZE",
    "DETAIL_URL",
    "IMAGE_BASE",
    "ParsedQuestion",
    "api_last_page",
    "detail_url",
    "figure_url",
    "listing_url",
    "parse_api_listing",
    "parse_api_question",
    "slug_for",
]

BASE: Final[str] = "https://myschool.ng"

#: Where a figure filename from the API resolves to.
IMAGE_BASE: Final[str] = f"{BASE}/storage/classroom"

#: The site uses one of these for a question with no figure. Downloading it
#: would put a placeholder in the bank under a question that has no diagram.
PLACEHOLDER_MARKERS: Final[tuple[str, ...]] = ("no_image_placeholder", "placeholder")

#: The API serves five rows a page and ignores ``per_page``.
API_PAGE_SIZE: Final[int] = 5

DETAIL_URL: Final[str] = BASE + "/classroom/{slug}/{item_id}?exam_type={exam}&exam_year={year}"


@dataclass(frozen=True)
class ParsedQuestion:
    """One trusted API row, in the source payload shape.

    ``exam`` and ``year`` are the row's collection, not the request. The
    source compares them before it files the row, because a response that
    answers a different paper is a source defect and not a silent import.
    """

    source_item_id: str
    source_url: str
    exam: str
    year: int
    payload: dict[str, Any]
    figures: tuple[str, ...] = ()


def slug_for(exam: str, subject: str) -> str:
    """The site's slug for a catalog subject, or a refusal."""
    return load_map().source_slug(exam, subject)


def listing_url(exam: str, subject_slug_value: str, year: int, page: int = 1) -> str:
    """The API URL for one page of one subject."""
    query = f"exam_type={exam}&exam_year={year}"
    if page > 1:
        query += f"&page={page}"
    return f"{BASE}/api/web/v1/classroom/{subject_slug_value}?{query}"


def detail_url(slug: str, item_id: str, exam: str, year: int) -> str:
    """Where a person can read the question, with its answer key."""
    return DETAIL_URL.format(slug=slug, item_id=item_id, exam=exam, year=year)


def parse_api_listing(payload: dict[str, Any], *, limit: int | None = None) -> list[dict[str, Any]]:
    """The question rows on one API page, in the order the site gave them."""
    if payload.get("status") is False:
        raise SourceError(
            "the api refused",
            message=str(payload.get("message", ""))[:200],
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise SourceError("the api response has no data object")
    practice = data.get("practice_questions")
    if not isinstance(practice, dict):
        raise SourceError("the api response has no practice_questions object")

    rows = practice.get("data")
    if not isinstance(rows, list):
        return []
    found = [row for row in rows if isinstance(row, dict)]
    if limit is not None:
        return found[:limit]
    return found


def api_last_page(payload: dict[str, Any]) -> int:
    """How many pages the API says there are, at least one."""
    data = payload.get("data")
    practice = data.get("practice_questions") if isinstance(data, dict) else None
    if not isinstance(practice, dict):
        return 1
    try:
        return max(1, int(practice.get("last_page", 1)))
    except (TypeError, ValueError):
        return 1


def figure_url(name: object) -> str | None:
    """The absolute URL of a figure, or ``None`` when there is not a real one.

    A bare filename is resolved against the classroom storage host. A path
    that already starts at the site root, a protocol-relative URL and an
    absolute URL are all kept. A placeholder or a non-http scheme is not a
    figure and is refused rather than downloaded.
    """
    if not isinstance(name, str):
        return None
    candidate = name.strip()
    if not candidate:
        return None
    if any(marker in candidate.lower() for marker in PLACEHOLDER_MARKERS):
        return None
    if candidate.startswith(("http://", "https://")):
        return candidate
    if candidate.startswith("//"):
        return f"https:{candidate}"
    if candidate.startswith(("/", "storage/")):
        return f"{BASE}/{candidate.lstrip('/')}"
    if candidate.startswith(("data:", "javascript:", "mailto:")):
        return None
    return f"{IMAGE_BASE}/{candidate.lstrip('/')}"


def parse_api_question(
    row: dict[str, Any],
    *,
    exam: str,
    subject: str,
    year: int,
    source_slug: str | None = None,
) -> ParsedQuestion:
    """One API row into a payload, or a refusal naming what was wrong.

    ``subject`` is the production catalog slug and travels with the row. The
    API's subject slug is only needed to build the human URL, so the caller
    passes it as ``source_slug``.
    """
    item_id = str(row.get("id", "")).strip()
    if not item_id:
        raise SourceError("api row has no id")

    markup = row.get("question")
    if not isinstance(markup, str) or not markup.strip():
        raise SourceError("api row has no question text", item_id=item_id)

    stem_text, stem_marks = clean_inline(markup)
    if not stem_text:
        raise SourceError(
            "api row's question text is empty once tags are stripped", item_id=item_id
        )

    raw_options = row.get("options")
    if not isinstance(raw_options, list):
        raise SourceError("api row has no options array", item_id=item_id)

    options: list[dict[str, Any]] = []
    answer = ""
    seen: set[str] = set()
    for entry in sorted(
        (option for option in raw_options if isinstance(option, dict)),
        key=lambda option: str(option.get("tag", "")),
    ):
        tag = str(entry.get("tag", "")).strip().lower()[:1]
        description = entry.get("description")
        if not tag or not isinstance(description, str) or not description.strip():
            continue
        if tag in seen:
            continue
        seen.add(tag)
        body, body_marks = clean_inline(description)
        if not body:
            continue
        options.append(
            {
                "id": tag.upper(),
                "text": body,
                "inline": [mark.model_dump(mode="json") for mark in body_marks],
            }
        )
        if entry.get("is_correct"):
            answer = tag.upper()

    if len(options) < 2:
        raise SourceError(
            "fewer than two usable options",
            item_id=item_id,
            found=len(options),
        )
    if not answer:
        raise SourceError(
            "the api marked no option correct",
            item_id=item_id,
            options=[option["id"] for option in options],
        )

    figures: list[str] = []
    marks: list[Inline] = []
    for mark in stem_marks:
        if mark.kind is not InlineKind.IMAGE:
            marks.append(mark)
            continue
        resolved = figure_url(mark.url)
        if resolved is None:
            continue
        marks.append(mark.model_copy(update={"url": resolved, "position": ImagePosition.BELOW}))
        if resolved not in figures:
            figures.append(resolved)

    main_figure = figure_url(row.get("image"))
    if main_figure is not None and main_figure not in figures:
        figures.append(main_figure)
        marks.append(
            Inline(
                kind=InlineKind.IMAGE,
                start=len(stem_text),
                len=0,
                url=main_figure,
                position=ImagePosition.BELOW,
            )
        )

    # Extract passage from ref field if present (myschool embeds stimuli here)
    passage = None
    ref = row.get("ref")
    if isinstance(ref, dict) and isinstance(ref.get("description"), str) and ref["description"].strip():
        passage_text, passage_marks = clean_inline(ref["description"])
        if passage_text:
            passage_id = str(ref.get("id", f"ref-{item_id}"))
            passage = {
                "id": passage_id,
                "text": passage_text,
                "inline": [mark.model_dump(mode="json") for mark in passage_marks],
                "kind": "Comprehension",
                "source_item_id": passage_id,
            }

    payload: dict[str, Any] = {
        "stem": stem_text,
        "stem_inline": [mark.model_dump(mode="json") for mark in marks],
        "options": options,
        "answer": answer,
        "marks": 1.0,
        "media": [
            {"key": f"figure-{index}", "url": url, "required": True}
            for index, url in enumerate(figures, start=1)
        ],
    }
    if passage is not None:
        payload["passage"] = passage

    collection = row.get("collection")
    row_exam = exam.lower()
    row_year = year
    if isinstance(collection, dict):
        if isinstance(collection.get("exam_type"), str):
            row_exam = str(collection["exam_type"]).lower()
        raw_year = collection.get("exam_year")
        if isinstance(raw_year, int) or (isinstance(raw_year, str) and raw_year.isdigit()):
            row_year = int(raw_year)

    source_url = (
        detail_url(source_slug, item_id, row_exam, row_year)
        if source_slug is not None
        else f"{listing_url(row_exam, subject, row_year)}#{item_id}"
    )
    return ParsedQuestion(
        source_item_id=item_id,
        source_url=source_url,
        exam=row_exam,
        year=row_year,
        payload=payload,
        figures=tuple(figures),
    )


def parse_json(text: str) -> dict[str, Any]:
    """A JSON response body as an object, or a source refusal."""
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise SourceError("the api response is not json", error=str(exc)) from exc
    if not isinstance(value, dict):
        raise SourceError("the api response is not an object")
    return value
