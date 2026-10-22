"""The live myschool API. Skipped unless ``UTMELAB_LIVE=1``.

The unit tests prove the parser against a recorded page. This one proves the
site still answers with the shape the parser expects, and it never touches the
database.
"""

from __future__ import annotations

import os

import pytest

from utmelab_bank.adapters.sources.myschool import MyschoolSource
from utmelab_bank.domain.models import Scope

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("UTMELAB_LIVE") != "1",
        reason="set UTMELAB_LIVE=1 to run live source smoke tests",
    ),
]


async def test_the_live_api_answers() -> None:
    source = MyschoolSource()
    scope = Scope(exam="JAMB", subject="physics", year=2025)
    try:
        coverage = await source.probe(scope)
        assert coverage.item_count > 0, "the api returned no rows for physics 2025"

        seen = 0
        async for item in source.fetch(scope):
            assert item.payload["stem"]
            assert item.payload["answer"]
            seen += 1
            if seen >= 5:
                break
        assert seen > 0
    finally:
        await source.close()
