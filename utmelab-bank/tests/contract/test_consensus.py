"""Contract tests for the consensus service."""

import asyncio
import pytest

from utmelab_pipeline.adapters.media import ConsensusPolicy, DescribeImageConsensus
from utmelab_pipeline.adapters.providers.mock import MockProvider
from utmelab_pipeline.domain.capabilities import DescribeImageRequest
from utmelab_pipeline.domain.models import MediaAsset, DescribeImageResponse
from datetime import datetime, UTC


class FailingDescriber:
    """A describer that always fails."""
    producer = MockProvider().producer

    async def describe(self, request):
        raise RuntimeError("Simulated failure")


def test_consensus_policy_reconcile():
    """ConsensusPolicy.reconcile returns majority description and union of facts."""
    from utmelab_pipeline.domain.models import Producer

    p1 = Producer(provider="mock", model="v1")
    p2 = Producer(provider="mock", model="v2")

    d1 = DescribeImageResponse(
        asset_id="a" * 64,
        description="A cell diagram",
        facts=("nucleus present",),
        confidence=0.9,
        producer=Producer(provider="p1", model="v1"),
    )
    d2 = DescribeImageResponse(
        asset_id="a" * 64,
        description="A cell diagram",
        facts=("membrane visible",),
        confidence=0.8,
        producer=Producer(provider="p2", model="v2"),
    )
    d3 = DescribeImageResponse(
        asset_id="a" * 64,
        description="A diagram of a cell",
        facts=("nucleus present", "membrane visible"),
        confidence=0.7,
        producer=Producer(provider="p3", model="v3"),
    )

    result = ConsensusPolicy.reconcile((d1, d2, d3))

    # Majority description wins
    assert result.description == "A cell diagram"
    # Facts union
    assert "nucleus present" in result.facts
    assert "membrane visible" in result.facts
    # Confidence averaged
    assert abs(result.confidence - 0.8) < 0.01
    # Producer is consensus
    assert result.producer.provider == "consensus"
    assert len(result.contributors) == 3


def test_consensus_single_description():
    """Single description returns as-is."""
    from utmelab_pipeline.domain.models import Producer

    d = DescribeImageResponse(
        asset_id="a" * 64,
        description="Single desc",
        facts=("fact1",),
        confidence=0.9,
        producer=Producer(provider="p1", model="v1"),
    )

    result = ConsensusPolicy.reconcile((d,))
    assert result is d


def test_consensus_no_descriptions_raises():
    with pytest.raises(ValueError, match="No descriptions"):
        ConsensusPolicy.reconcile(())


def test_consensus_with_failures():
    """Consensus continues even if some describers fail."""
    from utmelab_pipeline.adapters.providers.mock import MockProvider
    from utmelab_pipeline.domain.capabilities import DescribeImageRequest
    from utmelab_pipeline.domain.models import MediaAsset
    from datetime import datetime, UTC
    from utmelab_pipeline.adapters.media.consensus import DescribeImageConsensus

    async def run():
        mock = MockProvider()

        class FailingDescriber:
            producer = MockProvider().producer
            async def describe(self, req):
                raise RuntimeError("Simulated failure")

        consensus = DescribeImageConsensus(describers=(MockProvider(), FailingDescriber()))
        asset = MediaAsset(
            asset_id="a" * 64,
            mime="image/png",
            byte_size=10,
            width=10,
            height=10,
            storage_url="file:///tmp/test.png",
            fetched_at=datetime.now(UTC),
        )
        request = DescribeImageRequest(asset=asset, context="test")

        # Should not raise, should use the successful result
        result = await consensus.describe(request)
        assert result.description.startswith("Mock description for ")

    asyncio.run(run())