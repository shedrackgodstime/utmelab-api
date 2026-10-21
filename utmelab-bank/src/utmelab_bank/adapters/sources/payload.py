"""The source payload contract.

Every source adapts its own response into this one shape, and the rest of the
bank reads the shape. A fixture and a live scraper therefore produce the same
staging rows through the same code, which is the only way the fixture's tests
can say anything about the live path.

The payload is deliberately plain JSON: the source is the untrusted edge, so
the adapter validates it field by field instead of trusting a model to have
parsed it.
"""

from __future__ import annotations

from typing import Any

from utmelab_bank.domain.enums import (
    InlineKind,
    PassageKind,
)
from utmelab_bank.domain.models.common import (
    CatalogRef,
    CatalogSnapshot,
    Content,
    Inline,
    MediaRef,
    Option,
    Passage,
    Provenance,
    RichText,
    Scope,
    SourceItem,
    StagingItem,
)


def normalize_option_id(value: str) -> str:
    """The bank's option vocabulary is a to e, lower case.

    A source may print its labels as A, B, C or label them in another case.
    The gate owns the vocabulary, so the adapter is where the source's label
    becomes the bank's label instead of asking every later step to tolerate
    both.
    """
    return value.strip().lower()


def adapt_payload(item: SourceItem, catalog: CatalogSnapshot | None) -> StagingItem:
    """Adapt one source item into a staging item.

    The catalog is required only when the payload already names a catalog
    entry. A live scraper knows the exam, subject and year and nothing else,
    so it passes ``None`` and the catalogue step places the row later.
    """
    payload = item.payload
    catalog_ref = _catalog_ref(payload, item.scope, catalog)

    raw_options = payload.get("options")
    if not isinstance(raw_options, list):
        raise ValueError("payload options must be a list")
    options = tuple(_option(raw) for raw in raw_options)

    raw_marks = payload.get("marks")
    if isinstance(raw_marks, bool) or not isinstance(raw_marks, (int, float)):
        raise ValueError("payload marks must be a number")

    raw_answer = payload.get("answer")
    if not isinstance(raw_answer, str):
        raise ValueError("payload answer must be a string")
    answer = normalize_option_id(raw_answer)

    explanation = payload.get("explanation")
    source_explanation = (
        _rich_text(explanation, payload.get("explanation_inline"))
        if explanation is not None
        else None
    )

    raw_media = payload.get("media", [])
    if not isinstance(raw_media, list):
        raise ValueError("payload media must be a list")
    media_refs = tuple(_media_ref(raw) for raw in raw_media)

    passage = _passage(payload.get("passage"), item.scope)
    passage_id = passage.id if passage is not None else None

    content = Content(
        stem=_rich_text(payload.get("stem"), payload.get("stem_inline")),
        options=options,
        answer=answer,
        marks=float(raw_marks),
        passage_id=passage_id,
        source_explanation=source_explanation,
        section=item.scope.section,
    )

    staged = StagingItem(
        id=item.external_key,
        provenance=Provenance(
            source=item.source,
            source_url=item.source_url,
            source_item_id=item.source_item_id,
            fetched_at=item.fetched_at,
            payload_hash=item.payload_hash,
            source_version=item.source_version,
            scope=item.scope,
        ),
        content=content,
        passage=passage,
        media_refs=media_refs,
        catalog=catalog_ref,
        state="adapted",
        created_at=item.fetched_at,
        updated_at=item.fetched_at,
    )
    return staged.stamp_hashes()


def validate_payload(payload: dict[str, Any]) -> list[str]:
    """The source-level checks, before any model or the gate sees the row.

    A placeholder item carries an ``error`` key instead of content. Reporting
    it here keeps a source refusal a per-row failure rather than a crash that
    loses the rest of the page.
    """
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        return [f"source.error: {error}"]

    issues: list[str] = []

    stem = payload.get("stem")
    if not isinstance(stem, str) or not stem.strip():
        issues.append("source.stem: stem is missing")

    option_ids = _check_options(payload.get("options"))
    issues.extend(_check_answer(payload.get("answer"), option_ids))
    media_urls = _check_media(payload.get("media", []))
    issues.extend(_check_stem_inline(payload.get("stem_inline", []), media_urls))
    return issues


def _catalog_ref(
    payload: dict[str, Any],
    scope: Scope,
    catalog: CatalogSnapshot | None,
) -> CatalogRef | None:
    topic_id = payload.get("topic_id")
    subtopic_id = payload.get("subtopic_id")
    if topic_id is None and subtopic_id is None:
        return None
    if not isinstance(topic_id, str) or not isinstance(subtopic_id, str):
        raise ValueError("payload must name topic_id and subtopic_id")
    if catalog is None:
        raise ValueError("the payload names catalog ids but no catalog was read")
    subtopic = next((s for s in catalog.subtopics if s.id == subtopic_id), None)
    if subtopic is None or subtopic.topic_id != topic_id:
        raise ValueError(f"catalog has no subtopic {subtopic_id!r} under topic {topic_id!r}")
    return CatalogRef(
        exam=scope.exam,
        subject=scope.subject,
        year=scope.year,
        section=scope.section,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        catalog_version=catalog.version,
    )


def _check_options(raw_options: object) -> list[str]:
    option_ids: list[str] = []
    if not isinstance(raw_options, list) or len(raw_options) < 2:
        return option_ids
    for raw in raw_options:
        if not isinstance(raw, dict):
            continue
        option_id = raw.get("id")
        text = raw.get("text")
        if isinstance(option_id, str) and isinstance(text, str) and text.strip():
            option_ids.append(normalize_option_id(option_id))
    return option_ids


def _check_answer(answer: object, option_ids: list[str]) -> list[str]:
    if not isinstance(answer, str) or not answer.strip():
        return ["source.answer: answer is missing"]
    if normalize_option_id(answer) not in option_ids:
        return ["source.answer: answer is not one of the options"]
    return []


def _check_media(raw_media: object) -> list[str]:
    media_urls: list[str] = []
    if not isinstance(raw_media, list):
        return media_urls
    for raw in raw_media:
        if not isinstance(raw, dict):
            continue
        key = raw.get("key")
        url = raw.get("url")
        if isinstance(key, str) and isinstance(url, str):
            media_urls.append(url)
    return media_urls


def _check_stem_inline(raw_inline: object, media_urls: list[str]) -> list[str]:
    issues: list[str] = []
    if not isinstance(raw_inline, list):
        return issues
    for index, raw in enumerate(raw_inline):
        if not isinstance(raw, dict):
            continue
        if raw.get("kind") == InlineKind.IMAGE.value:
            url = raw.get("url")
            if not isinstance(url, str) or url not in media_urls:
                issues.append(f"source.mark: stem mark {index} references an unknown media url")
    return issues


def _option(raw: object) -> Option:
    if not isinstance(raw, dict):
        raise ValueError("option must be an object")
    option_id = raw.get("id")
    text = raw.get("text")
    if not isinstance(option_id, str) or not isinstance(text, str):
        raise ValueError("option needs an id and text")
    return Option(
        id=normalize_option_id(option_id),
        text=_rich_text(text, raw.get("inline")),
    )


def _passage(raw: object, scope: Scope) -> Passage | None:
    """Build a passage in the production shape.

    The scope supplies the exam, subject and year, so a passage cannot
    arrive without them, and the kind comes from the source because only
    the source knows whether the text is a story, a cloze, a reading or a
    set of numbers.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("passage must be an object")
    passage_id = raw.get("id")
    text = raw.get("text")
    source_item_id = raw.get("source_item_id")
    if not isinstance(passage_id, str) or not isinstance(text, str):
        raise ValueError("passage needs an id and text")
    if source_item_id is not None and not isinstance(source_item_id, str):
        raise ValueError("passage source_item_id must be a string")
    kind = raw.get("kind")
    if not isinstance(kind, str):
        raise ValueError("passage needs a kind")
    return Passage(
        id=passage_id,
        exam=scope.exam,
        subject=scope.subject,
        year=scope.year,
        kind=PassageKind(kind),
        title=raw.get("title") if isinstance(raw.get("title"), str) else None,
        author=raw.get("author") if isinstance(raw.get("author"), str) else None,
        text=_rich_text(text, raw.get("inline")),
        source_item_id=source_item_id,
    )


def _media_ref(raw: object) -> MediaRef:
    if not isinstance(raw, dict):
        raise ValueError("media entry must be an object")
    key = raw.get("key")
    url = raw.get("url")
    if not isinstance(key, str) or not isinstance(url, str):
        raise ValueError("media entry needs a key and url")
    mime = raw.get("mime")
    alt = raw.get("alt")
    required = raw.get("required", False)
    if mime is not None and not isinstance(mime, str):
        raise ValueError("media mime must be a string")
    if alt is not None and not isinstance(alt, str):
        raise ValueError("media alt must be a string")
    if not isinstance(required, bool):
        raise ValueError("media required must be a boolean")
    return MediaRef(key=key, source_url=url, mime=mime, alt=alt, required=required)


def _rich_text(text: object, raw_marks: object) -> RichText:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("rich text must be a non-empty string")
    inline: list[Inline] = []
    if raw_marks is not None:
        if not isinstance(raw_marks, list):
            raise ValueError("inline must be a list")
        for raw in raw_marks:
            inline.append(_mark(raw))
    return RichText(text=text, inline=tuple(inline))


def _mark(raw: object) -> Inline:
    if not isinstance(raw, dict):
        raise ValueError("mark must be an object")
    kind = raw.get("kind")
    start = raw.get("start")
    length = raw.get("len")
    url = raw.get("url")
    position = raw.get("position")
    if not isinstance(kind, str):
        raise ValueError("mark kind must be a string")
    if isinstance(start, bool) or not isinstance(start, int):
        raise ValueError("mark start must be an integer")
    if isinstance(length, bool) or not isinstance(length, int):
        raise ValueError("mark len must be an integer")
    if url is not None and not isinstance(url, str):
        raise ValueError("mark url must be a string")
    if position is not None and not isinstance(position, str):
        raise ValueError("mark position must be a string")
    return Inline(
        kind=kind,
        start=start,
        len=length,
        url=url,
        position=position,
        alt=raw.get("alt"),
    )


__all__ = [
    "adapt_payload",
    "normalize_option_id",
    "validate_payload",
]
