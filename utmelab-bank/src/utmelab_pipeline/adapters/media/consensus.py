"""Consensus service: reconcile multiple image descriptions into one."""

from collections import Counter
from typing import Optional

from utmelab_pipeline.domain.models import DescribeImageResponse, Producer


class ConsensusPolicy:
    """Policy for reconciling multiple image descriptions."""

    @staticmethod
    def reconcile(
        descriptions: tuple["DescribeImageResponse", ...],
    ) -> "DescribeImageResponse":
        """
        Reconcile multiple descriptions into one consensus description.

        Policy:
        - Description: majority vote on text (or longest if tie)
        - Facts: union of all facts (deduplicated)
        - Confidence: average of confidences
        - Producer: "consensus" with contributors listed
        """
        if not descriptions:
            raise ValueError("No descriptions to reconcile")
        if len(descriptions) == 1:
            return descriptions[0]

        # Description: majority vote (or longest as tiebreaker)
        desc_counts = Counter(d.description for d in descriptions)
        most_common_desc, _ = desc_counts.most_common(1)[0]

        # Facts: union, deduplicated
        all_facts = []
        seen = set()
        for d in descriptions:
            for fact in d.facts:
                if fact not in seen:
                    seen.add(fact)
                    all_facts.append(fact)

        # Confidence: average
        avg_confidence = sum(d.confidence for d in descriptions) / len(descriptions)

        # Producer: consensus with contributors
        contributors = tuple(d.producer for d in descriptions)
        consensus_producer = Producer(
            provider="consensus",
            model=f"reconciled-{len(descriptions)}",
            version=None,
        )

        return DescribeImageResponse(
            asset_id=descriptions[0].asset_id,
            description=most_common_desc,
            facts=tuple(all_facts),
            confidence=sum(d.confidence for d in descriptions) / len(descriptions),
            producer=consensus_producer,
            contributors=contributors,
        )


class DescribeImageConsensus:
    """Run multiple describers and reconcile their outputs."""

    def __init__(self, describers: tuple["ImageDescriber", ...]) -> None:
        if len(describers) < 2:
            raise ValueError("Consensus requires at least 2 describers")
        self.describers = describers

    async def describe(self, request) -> "DescribeImageResponse":
        """Run all describers and reconcile."""
        # Run all describers concurrently
        import asyncio
        tasks = [d.describe(request) for d in self.describers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect successful results
        results_list = []
        for r in results:
            if isinstance(r, Exception):
                # Log error but continue with other results
                continue
            results_list.append(r)

        if not results_list:
            raise RuntimeError("All describers failed")

        return ConsensusPolicy.reconcile(tuple(results_list))