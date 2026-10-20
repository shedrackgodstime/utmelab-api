"""Contract tests for the consensus service."""

import asyncio
from datetime import UTC, datetime

import pytest

from utmelab_pipeline.adapters.media import ConsensusPolicy, DescribeImageConsensus
from utmelab_pipeline.adapters.providers.mock import MockProvider
from utmelab_pipeline.domain.capabilities import DescribeImageRequest
from utmelab_pipeline.domain.models import ImageDescription, MediaAsset, Producer


def make_asset() -> MediaAsset:
    return MediaAsset(
        asset_id="a" * 64,
        mime="image/png",
        byte_size=10,
        width=10,
        height=10,
        storage_url="file:///tmp/test.png",
        fetched_at=datetime.now(UTC),
    )


def test_consensus_policy_reconcile() -> None:
    d1 = ImageDescription(
        asset_id="a" * 64,
        description="A cell diagram",
        facts=("nucleus present",),
        confidence=0.9,
        producer=Producer(provider="p1", model="v1"),
    )
    d2 = ImageDescription(
        asset_id="a" * 64,
        description="A cell diagram",
        facts=("membrane visible",),
        confidence=0.8,
        producer=Producer(provider="p2", model="v2"),
    )
    d3 = ImageDescription(
        asset_id="a" * 64,
        description="A diagram of a cell",
        facts=("nucleus present", "membrane visible"),
        confidence=0.7,
        producer=Producer(provider="p3", model="v3"),
    )

    result = ConsensusPolicy.reconcile((d1, d2, d3))

    assert result.description == "A cell diagram"
    assert "nucleus present" in result.facts
    assert "membrane visible" in result.facts
    assert abs(result.confidence - 0.8) < 0.01
    assert result.producer.provider == "consensus"
    assert len(result.contributors) == 3


def test_consensus_single_description() -> None:
    d = ImageDescription(
        asset_id="a" * 64,
        description="Single desc",
        facts=("fact1",),
        confidence=0.9,
        producer=Producer(provider="p1", model="v1"),
    )

    result = ConsensusPolicy.reconcile((d,))
    assert result.description == d.description
    assert result.contributors == (d.producer,)


def test_consensus_no_descriptions_raises() -> None:
    with pytest.raises(ValueError, match="No descriptions"):
        ConsensusPolicy.reconcile(())


def test_consensus_with_failures() -> None:
    class FailingDescriber:
        producer = MockProvider().producer

        async def describe(self, request: DescribeImageRequest) -> ImageDescription:
            raise RuntimeError("Simulated failure")

    async def run() -> ImageDescription:
        consensus = DescribeImageConsensus(
            describers=(MockProvider(), FailingDescriber())
        )
        request = DescribeImageRequest(asset=make_asset(), context="test")
        return await consensus.describe(request)

    result = asyncio.run(run())
    assert result.description.startswith("Mock description for ")
    assert len(result.contributors) == 1
