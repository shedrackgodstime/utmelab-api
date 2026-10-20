"""Model output. Every value here is a proposal until the core accepts it."""

from pydantic import Field, model_validator

from ..enums import Verdict
from .common import Confidence, DomainModel, NonEmptyStr, Producer, RichText, Sha256


class ImageDescription(DomainModel):
    asset_id: Sha256
    description: NonEmptyStr
    facts: tuple[NonEmptyStr, ...] = ()
    confidence: Confidence
    producer: Producer
    contributors: tuple[Producer, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "ImageDescription":
        if len(set(self.contributors)) != len(self.contributors):
            raise ValueError("contributors must be unique")
        return self


class TagProposal(DomainModel):
    topic_id: NonEmptyStr
    subtopic_id: NonEmptyStr
    evidence: NonEmptyStr
    confidence: Confidence
    producer: Producer


class Explanation(DomainModel):
    key_point: RichText
    body: RichText
    trap: RichText | None = None
    confidence: Confidence
    producer: Producer


class AnswerVerdict(DomainModel):
    verdict: Verdict
    reasoning: NonEmptyStr
    confidence: Confidence
    producer: Producer


class DescribeImageResponse(DomainModel):
    asset_id: Sha256
    description: NonEmptyStr
    facts: tuple[NonEmptyStr, ...] = ()
    confidence: Confidence
    producer: Producer
    contributors: tuple[Producer, ...] = ()
