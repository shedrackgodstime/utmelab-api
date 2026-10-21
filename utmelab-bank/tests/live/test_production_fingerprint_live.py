"""A live contract test: every production row must hash the same way.

The content fingerprint is the receipt that ties a review to the content it
reviewed, and the serving predicate compares the stored hash with the one
the review covered. If our hash differs from production's by one byte, the
row falls out of service the moment its content is touched.

So this checks all the live rows, with the model's own parsing in the loop.

It is skipped unless ``UTMELAB_LIVE=1`` is set, because it needs the network.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from utmelab_bank.adapters.catalog.client import TursoClient
from utmelab_bank.config import load_settings
from utmelab_bank.domain.hashing import content_fingerprint

from tests.live.production_rows import StoredExplanation, option, rich

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("UTMELAB_LIVE") != "1",
        reason="set UTMELAB_LIVE=1 to run live provider smoke tests",
    ),
]


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
        raw = json.loads(explanation) if explanation else None
        ours = content_fingerprint(
            stem=rich({"text": text, "inline": json.loads(inline or "[]")}),
            options=tuple(option(raw) for raw in json.loads(options)),
            answer=answer,
            explanation=StoredExplanation(raw) if raw else None,
        )
        if ours != stored:
            mismatched.append((qid, stored, ours))

    assert not mismatched, (
        f"{len(mismatched)} of {len(result.rows)} production rows do not hash "
        f"the way we hash them: {mismatched[:3]}"
    )
