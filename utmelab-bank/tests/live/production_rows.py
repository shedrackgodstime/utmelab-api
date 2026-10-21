"""Reading production rows into the bank's own models.

Both live contract tests need the same thing: a production row turned into
the bank's model classes, so that the model's parsing is tested alongside
the hash and the gate. It lives here so there is one copy.
"""

from __future__ import annotations

import json
from typing import Any

from utmelab_bank.domain.models.common import Content, Option, RichText


def rich(raw: dict[str, Any]) -> RichText:
    """A production text object, which is a text and its inline list."""
    return RichText.model_validate(
        {"text": raw["text"], "inline": raw.get("inline") or []}
    )


def option(raw: dict[str, Any]) -> Option:
    """A production option, which is an id and a text object."""
    return Option.model_validate(
        {
            "id": raw["id"],
            "text": {
                "text": raw["text"]["text"],
                "inline": raw["text"].get("inline") or [],
            },
        }
    )


def content(
    text: str,
    inline: str,
    options: str,
    answer: str,
    explanation: str | None,
    marks: float,
) -> Content:
    """A production row's content, in the bank's shape."""
    source_explanation = None
    if explanation:
        raw = json.loads(explanation)
        body = raw.get("body") or raw.get("key_point")
        if body:
            source_explanation = rich(body)
    return Content(
        stem=rich({"text": text, "inline": json.loads(inline or "[]")}),
        options=tuple(option(raw) for raw in json.loads(options)),
        answer=answer,
        marks=marks,
        source_explanation=source_explanation,
    )


class StoredExplanation:
    """Only the three parts the fingerprint reads."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.key_point = rich(raw["key_point"])
        self.body = rich(raw["body"])
        trap = raw.get("trap")
        self.trap = rich(trap) if trap is not None else None


__all__ = ["StoredExplanation", "content", "option", "rich"]
