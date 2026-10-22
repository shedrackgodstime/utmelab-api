"""Consensus service: reconcile multiple image descriptions into one."""

import asyncio
from collections import Counter

from utmelab_bank.domain.capabilities import DescribeImageRequest
from utmelab_bank.domain.models import ImageDescription, Producer
from utmelab_bank.domain.ports import ImageDescriber


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


class WitnessError(RuntimeError):
    """A witness was missing or dissented, so the asset is not trusted."""


class MissingWitness(WitnessError):
    """At least one witness did not answer."""


class Dissent(WitnessError):
    """The witnesses answered, and did not agree."""


class DescribeImageConsensus:
    """Run several describers and reconcile what they return.

    This is a check, not a poll, and it fails closed. Two rules make it one:

    - **The witnesses have to be different models.** Two runs of one model
      agree because they are the same model, which proves nothing. A repeated
      witness is refused when the policy is built.
    - **Every witness has to answer, and the answer has to win a majority.**
      A witness that errors is a missing witness, and a set of descriptions
      with no majority is a dissent. Either one refuses the asset, so a
      figure nothing agrees on never reaches a row.
    """

    def __init__(self, describers: tuple[ImageDescriber, ...]) -> None:
        if len(describers) < 2:
            raise ValueError("Consensus requires at least 2 describers")
        identities = [(d.producer.provider, d.producer.model) for d in describers]
        if len(set(identities)) != len(identities):
            raise ValueError("every witness must be a different model")
        self._describers = describers
        self.producer = Producer(
            provider="consensus",
            model=f"reconciled-{len(describers)}",
        )

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
        if len(good) != len(self._describers):
            missing = len(self._describers) - len(good)
            raise MissingWitness(f"{missing} of {len(self._describers)} witnesses did not answer")

        counts = Counter(description.description for description in good)
        winner = counts.most_common(1)[0][1]
        if winner * 2 <= len(good):
            raise Dissent("the witnesses did not agree on what the figure shows")

        return ConsensusPolicy.reconcile(tuple(good))
