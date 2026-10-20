"""Consensus service: reconcile multiple image descriptions into one."""

import asyncio
from collections import Counter

from utmelab_pipeline.domain.capabilities import DescribeImageRequest
from utmelab_pipeline.domain.models import ImageDescription, Producer
from utmelab_pipeline.domain.ports import ImageDescriber


class ConsensusPolicy:
    """Policy for reconciling multiple image descriptions."""

    @staticmethod
    def reconcile(
        descriptions: tuple[ImageDescription, ...],
    ) -> ImageDescription:
        """
        Reconcile multiple descriptions into one consensus description.

        Policy:
        - Description: majority vote, longest wins a tie
        - Facts: union of all facts, deduplicated
        - Confidence: mean of the confidences
        - Producer: the consensus, with every contributor listed
        """
        if not descriptions:
            raise ValueError("No descriptions to reconcile")
        if len(descriptions) == 1:
            only = descriptions[0]
            return only.model_copy(update={"contributors": (only.producer,)})

        counts = Counter(d.description for d in descriptions)
        most_common = max(counts.items(), key=lambda pair: (pair[1], len(pair[0])))
        description = most_common[0]

        facts: list[str] = []
        seen: set[str] = set()
        for item in descriptions:
            for fact in item.facts:
                if fact not in seen:
                    seen.add(fact)
                    facts.append(fact)

        contributors = tuple(d.producer for d in descriptions)
        return ImageDescription(
            asset_id=descriptions[0].asset_id,
            description=description,
            facts=tuple(facts),
            confidence=sum(d.confidence for d in descriptions) / len(descriptions),
            producer=Producer(
                provider="consensus",
                model=f"reconciled-{len(descriptions)}",
            ),
            contributors=contributors,
        )


class DescribeImageConsensus:
    """Run several describers and reconcile what they return."""

    def __init__(self, describers: tuple[ImageDescriber, ...]) -> None:
        if len(describers) < 2:
            raise ValueError("Consensus requires at least 2 describers")
        self._describers = describers

    async def describe(self, request: DescribeImageRequest) -> ImageDescription:
        results = await asyncio.gather(
            *(d.describe(request) for d in self._describers),
            return_exceptions=True,
        )
        good: list[ImageDescription] = []
        for result in results:
            if isinstance(result, BaseException):
                continue
            good.append(result)
        if not good:
            raise RuntimeError("Every describer failed")
        return ConsensusPolicy.reconcile(tuple(good))
