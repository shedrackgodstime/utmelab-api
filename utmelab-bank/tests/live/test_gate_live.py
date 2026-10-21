"""A live contract test: the gate must see what the live bank shows.

The bank's gate is the only quality control the content gets, because the
serving side does not validate rows. So the gate's behaviour is checked
against the live production rows, and the counts are pinned.

It is skipped unless ``UTMELAB_LIVE=1`` is set, because it needs the network.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from tests.live.production_rows import content
from utmelab_bank.adapters.database import TursoClient
from utmelab_bank.config import load_settings
from utmelab_bank.domain.gate import (
    GateContext,
    refusal_counts,
    run_gate,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("UTMELAB_LIVE") != "1",
        reason="set UTMELAB_LIVE=1 to run live provider smoke tests",
    ),
]


def test_the_gate_sees_the_live_bank_as_it_is() -> None:
    settings = load_settings()
    client = TursoClient(url=settings.prod_database_url, token=settings.prod_auth_token)
    rows: list[tuple[Any, ...]] = asyncio.run(
        client.execute(
            "SELECT text, inline, options, answer, explanation, marks, exam, subject, year "
            "FROM questions"
        )
    ).rows

    verdicts = []
    for row in rows:
        verdicts.append(
            run_gate(
                GateContext(
                    content=content(*row[:6]),
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
    #
    # There is no ``explanation_missing`` here, and that is deliberate. The
    # live tool refuses a row with no explanation because its pass has to
    # cover one, but the bank authors explanations at the enrich step, which
    # runs after the gate. The requirement lives in the ready condition
    # ``explanatory``. Of the 50 live rows without an explanation, 8 carry
    # another defect and 42 now pass the gate, which is why ``passed`` moved
    # from 2,178 to 2,220.
    assert counts == {
        "option_count": 11,
        "cloze_without_passage": 9,
        "missing_figure": 2,
        "exam_empty": 1,
    }, counts
    assert passed == 2220, passed
