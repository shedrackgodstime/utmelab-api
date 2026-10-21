"""A live contract test: every production row must hash the way we hash it.

This is the strongest check we have on the fingerprint. It runs against the
real production database and checks all 2,243 rows, so it covers the cases a
sample misses: rows with no explanation, rows with a trap, rows with an image
mark, and rows whose text carries a leading space.

It is skipped unless ``UTMELAB_LIVE=1`` is set, because it needs the network.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest

from utmelab_pipeline.adapters.catalog.client import TursoClient
from utmelab_pipeline.config import load_settings
from utmelab_pipeline.domain.hashing import content_fingerprint
from utmelab_pipeline.domain.models.common import Option, RichText

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("UTMELAB_LIVE") != "1",
        reason="set UTMELAB_LIVE=1 to run live provider smoke tests",
    ),
]


class StoredExplanation:
    """Only the three fields the fingerprint reads."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.key_point = _rich(raw["key_point"])
        self.body = _rich(raw["body"])
        trap = raw.get("trap")
        self.trap = _rich(trap) if trap is not None else None


def _rich(raw: dict[str, Any]) -> RichText:
    return RichText.model_validate(
        {"text": raw["text"], "marks": raw.get("inline") or []}
    )


def test_every_production_row_hashes_the_same_way() -> None:
    settings = load_settings()
    client = TursoClient(
        url=settings.prod_database_url, token=settings.prod_auth_token
    )
    result = asyncio.run(
        client.execute(
            "SELECT id, text, inline, options, answer, explanation, content_hash "
            "FROM questions"
        )
    )

    mismatched: list[tuple[str, str, str]] = []
    for qid, text, inline, options, answer, explanation, stored in result.rows:
        stem = RichText.model_validate(
            {"text": text, "marks": json.loads(inline or "[]")}
        )
        parsed_options = [
            Option.model_validate(
                {
                    "id": option["id"],
                    "text": {
                        "text": option["text"]["text"],
                        "marks": option["text"].get("inline") or [],
                    },
                }
            )
            for option in json.loads(options)
        ]
        stored_explanation = (
            StoredExplanation(json.loads(explanation)) if explanation else None
        )
        ours = content_fingerprint(
            stem=stem,
            options=parsed_options,
            answer=answer,
            explanation=stored_explanation,
        )
        if ours != stored:
            mismatched.append((qid, stored, ours))

    assert not mismatched, (
        f"{len(mismatched)} of {len(result.rows)} production rows do not hash "
        f"the way we hash them: {mismatched[:3]}"
    )
