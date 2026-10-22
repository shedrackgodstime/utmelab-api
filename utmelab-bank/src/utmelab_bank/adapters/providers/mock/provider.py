"""A deterministic provider used to prove the capability ports."""

from utmelab_bank.domain.capabilities import (
    DescribeImageRequest,
    ExplainRequest,
    TagRequest,
    VerifyAnswerRequest,
)
from utmelab_bank.domain.enums import Capability, Verdict
from utmelab_bank.domain.models import (
    AnswerVerdict,
    Explanation,
    ImageDescription,
    Producer,
    RichText,
    TagProposal,
)


class MockProvider:
    """Returns stable proposals so the core can be tested without a model."""

    capabilities = frozenset(Capability)

    def __init__(
        self,
        *,
        producer: Producer | None = None,
        confidence: float = 1.0,
        verdict: Verdict = Verdict.PASS,
    ) -> None:
        self.producer = producer or Producer(provider="mock", model="mock-v1")
        self._confidence = confidence
        self._verdict = verdict

    async def describe(self, request: DescribeImageRequest) -> ImageDescription:
        return ImageDescription(
            asset_id=request.asset.asset_id,
            description=f"Mock description for {request.asset.asset_id}",
            facts=("The asset is an image.",),
            confidence=self._confidence,
            producer=self.producer,
        )

    async def explain(self, request: ExplainRequest) -> Explanation:
        return Explanation(
            key_point=RichText(text="Mock key point"),
            body=RichText(text=f"Mock explanation for: {request.item.content.stem.text}"),
            confidence=self._confidence,
            producer=self.producer,
        )

    async def tag(self, request: TagRequest) -> TagProposal:
        subtopic = request.catalog.subtopics[0]
        return TagProposal(
            topic_id=subtopic.topic_id,
            subtopic_id=subtopic.id,
            evidence=request.item.content.stem.text,
            confidence=self._confidence,
            producer=self.producer,
        )

    async def verify(self, request: VerifyAnswerRequest) -> AnswerVerdict:
        return AnswerVerdict(
            verdict=self._verdict,
            reasoning="Mock verification of the canonical answer.",
            confidence=self._confidence,
            producer=self.producer,
        )
