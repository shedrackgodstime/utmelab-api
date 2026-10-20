import asyncio
import os

import pytest

from utmelab_pipeline.adapters.providers.opencode import OpenCodeProvider
from utmelab_pipeline.domain.capabilities import ExplainRequest
from utmelab_pipeline.domain.models import StagingItem

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("UTMELAB_LIVE") != "1",
        reason="set UTMELAB_LIVE=1 to run live provider smoke tests",
    ),
]


def test_opencode_explain_live(staging_item: StagingItem) -> None:
    model = os.environ.get(
        "UTMELAB_OPENCODE_MODEL",
        "opencode/deepseek-v4.1-flash-free",
    )
    provider = OpenCodeProvider(model=model, timeout=120.0)
    result = asyncio.run(provider.explain(ExplainRequest(item=staging_item, catalog=None)))
    assert result.body
    assert result.producer.provider == "opencode"