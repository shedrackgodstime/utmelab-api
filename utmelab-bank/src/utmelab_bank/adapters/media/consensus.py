"""Consensus service: reconcile multiple image descriptions into one.

Two models that see the same figure describe it in different words: "a farm
tool" versus "a wheeled agricultural implement". Comparing the strings word for
word would refuse every same-figure pair, which is why this service does not
compare strings at all. One witness describes, a different witness verifies
that description against the figure, and only a pass lets it onto a row. That
is the same shape the bank uses for answers: a producer and a verifier, and
the verifier has to be a different model.
"""

from __future__ import annotations

import asyncio
from collections import Counter

from utmelab_bank.domain.capabilities import (
    DescribeImageRequest,
    VerifyDescriptionRequest,
)
from utmelab_bank.domain.enums import Verdict
from utmelab_bank.domain.models import ImageDescription, Producer
from utmelab_bank.domain.ports import ImageWitness


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
    - **A description is verified by a different witness.** Two descriptions
      of one figure will never match word for word, because one model says
      "farm tool" and the other says "wheeled agricultural implement". So the
      richest description is the primary, and a witness that did not write it
      looks at the figure and judges it. Only a pass lets the description
      onto a row; a fail, an abstention, or a missing witness refuses the
      figure, so a description nothing confirms never reaches a row.
    """

    def __init__(self, describers: tuple[ImageWitness, ...]) -> None:
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

        primary = max(good, key=lambda item: len(item.description))
        verifier = next(
            d
            for d in self._describers
            if (d.producer.provider, d.producer.model)
            != (primary.producer.provider, primary.producer.model)
        )
        try:
            verdict = await verifier.verify_description(
                VerifyDescriptionRequest(
                    asset=request.asset,
                    description=primary.description,
                    facts=primary.facts,
                    context=request.context,
                    data=request.data,
                )
            )
        except Exception as exc:
            raise MissingWitness(
                f"witness {verifier.producer.model} did not verify: {exc}"
            ) from exc
        if verdict.verdict is not Verdict.PASS:
            raise Dissent("the witnesses did not agree on what the figure shows")

        return ConsensusPolicy.reconcile(tuple(good))
