"""A live contract test: the dedupe must catch a production row.

The dedupe is what stops the bank from producing the same question twice,
and the served bank is the thing it is checked against. So the test takes a
real production row, feeds it back in, and expects it to be refused.

It is skipped unless ``UTMELAB_LIVE=1`` is set, because it needs the network.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
import pytest

from utmelab_bank.adapters.database import bank_client, prod_client
from utmelab_bank.adapters.dedupe_service import DedupeService
from utmelab_bank.adapters.index_refresh import IndexRefresher
from utmelab_bank.adapters.production import ProductionContentReader
from utmelab_bank.adapters.store.index import PRODUCTION, ContentIndexStore
from utmelab_bank.adapters.store.staging import StagingStore
from utmelab_bank.config import load_settings
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import (
    Content,
    Hashes,
    Option,
    Provenance,
    RichText,
    Scope,
    StagingItem,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("UTMELAB_LIVE") != "1",
        reason="set UTMELAB_LIVE=1 to run live provider smoke tests",
    ),
]


async def test_a_production_row_fed_back_in_is_refused() -> None:
    settings = load_settings()
    bank = bank_client(settings)
    prod = prod_client(settings)
    await StagingStore(bank).prepare()
    index = ContentIndexStore(bank)
    reader = ProductionContentReader(prod)
    await IndexRefresher(index, reader).refresh()

    result = await prod.execute(
        "SELECT id, text, options, answer, content_hash FROM questions LIMIT 1"
    )
    qid, text, options, answer, content_hash = result.rows[0]

    now = datetime.now(UTC)
    item = StagingItem(
        id="probe:1",
        provenance=Provenance(
            source="probe",
            source_url="https://example.com/probe",
            source_item_id="1",
            fetched_at=now,
            payload_hash="b" * 64,
            source_version="1",
            scope=Scope(exam="JAMB", subject="mathematics", year=2025),
        ),
        content=Content(
            stem=RichText.model_validate({"text": text, "inline": []}),
            options=tuple(
                Option.model_validate(
                    {
                        "id": option["id"],
                        "text": {
                            "text": option["text"]["text"],
                            "inline": option["text"].get("inline") or [],
                        },
                    }
                )
                for option in json.loads(options)
            ),
            answer=answer,
            marks=1.0,
        ),
        state=State.GATED,
        hashes=Hashes(
            payload_hash="b" * 64, content_hash=content_hash, bundle_hash="d" * 64
        ),
        created_at=now,
        updated_at=now,
    )

    verdict = await DedupeService(index).apply(item)

    assert verdict.state is State.REJECTED
    assert verdict.error is not None
    assert "duplicate_exact" in verdict.error
    assert qid in verdict.error


async def test_the_index_holds_every_production_question() -> None:
    settings = load_settings()
    bank = bank_client(settings)
    prod = prod_client(settings)
    await StagingStore(bank).prepare()
    index = ContentIndexStore(bank)
    reader = ProductionContentReader(prod)
    count = await IndexRefresher(index, reader).refresh()

    total = await prod.execute("SELECT count(*) FROM questions")

    assert count == total.rows[0][0]
    assert await index.count(PRODUCTION) == total.rows[0][0]
