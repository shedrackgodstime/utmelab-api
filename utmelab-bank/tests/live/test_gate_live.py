"""A live contract test: the gate must see what the live bank shows.

The bank's gate is the only quality control the content gets, because the
serving side does not validate rows. So the gate's behaviour is checked
against the live production rows, and the counts are pinned.

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
from utmelab_pipeline.domain.gate import (
    GateContext,
    refusal_counts,
    run_gate,
)
from utmelab_pipeline.domain.models.common import Content, Option, RichText

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("UTMELAB_LIVE") != "1",
        reason="set UTMELAB_LIVE=1 to run live provider smoke tests",
    ),
]


def _rich(raw: dict[str, Any]) -> RichText:
    return RichText.model_validate(
        {"text": raw["text"], "marks": raw.get("inline") or []}
    )


def build_content(row: tuple[Any, ...]) -> Content:
    text, inline, options, answer, explanation = row[:5]
    parsed = [
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
    source_explanation = None
    if explanation:
        raw = json.loads(explanation)
        body = raw.get("body") or raw.get("key_point")
        if body:
            source_explanation = _rich(body)
    return Content(
        stem=_rich({"text": text, "inline": json.loads(inline or "[]")}),
        options=tuple(parsed),
        answer=answer,
        marks=float(row[5]),
        source_explanation=source_explanation,
    )


def test_the_gate_sees_the_live_bank_as_it_is() -> None:
    settings = load_settings()
    client = TursoClient(url=settings.prod_database_url, token=settings.prod_auth_token)
    rows = asyncio.run(
        client.execute(
            "SELECT text, inline, options, answer, explanation, marks, exam, subject, year "
            "FROM questions"
        )
    ).rows

    verdicts = []
    for row in rows:
        content = build_content(row)
        verdicts.append(
            run_gate(
                GateContext(
                    content=content,
                    exam=row[6],
                    subject=row[7],
                    year=row[8],
                )
            )
        )

    counts = refusal_counts(verdicts)
    passed = sum(1 for verdict in verdicts if verdict.passed)

    # The live bank, as the bank's own gate judges it. These are the counts
    # that say the gate is looking at the same defects a person would.
    assert counts == {
        "explanation_missing": 50,
        "option_count": 11,
        "cloze_without_passage": 9,
        "missing_figure": 2,
        "exam_empty": 1,
    }, counts
    assert passed == 2178, passed
