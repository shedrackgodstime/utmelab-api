"""Shared value objects and constrained types."""

from typing import Annotated, Any, Optional, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

from ..enums import Severity

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
Slug = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
        strip_whitespace=True,
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
MimeType = Annotated[
    str,
    StringConstraints(
        pattern=r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$",
        strip_whitespace=True,
    ),
]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Year = Annotated[int, Field(ge=1980, le=2100)]
PositiveMarks = Annotated[float, Field(gt=0.0)]


class DomainModel(BaseModel):
    """Base for canonical values. Unknown fields are rejected on purpose."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class Scope(DomainModel):
    exam: NonEmptyStr
    subject: NonEmptyStr
    year: Year
    section: NonEmptyStr | None = None


class Producer(DomainModel):
    provider: NonEmptyStr
    model: NonEmptyStr
    version: NonEmptyStr | None = None


class Issue(DomainModel):
    code: NonEmptyStr
    message: NonEmptyStr
    severity: Severity
    field: NonEmptyStr | None = None


class Provenance(DomainModel):
    source: NonEmptyStr
    source_url: HttpUrl
    source_item_id: NonEmptyStr
    fetched_at: AwareDatetime
    payload_hash: Sha256
    source_version: NonEmptyStr
    scope: Scope

    @property
    def external_key(self) -> str:
        return f"{self.source}:{self.source_item_id}"


class Hashes(DomainModel):
    payload_hash: Sha256
    content_hash: Sha256
    bundle_hash: Sha256


class CatalogRef(DomainModel):
    """Reference to a catalog snapshot from production DB."""
    exam: NonEmptyStr
    subject: NonEmptyStr
    year: Year
    section: NonEmptyStr | None = None
    topic_id: NonEmptyStr
    subtopic_id: NonEmptyStr
    catalog_version: NonEmptyStr


class CatalogTopic(DomainModel):
    id: NonEmptyStr
    slug: Slug
    name: NonEmptyStr
    objectives: tuple[NonEmptyStr, ...] = ()


class CatalogSubtopic(DomainModel):
    id: NonEmptyStr
    slug: Slug
    name: NonEmptyStr
    topic_id: NonEmptyStr
    objectives: tuple[NonEmptyStr, ...] = ()


class CatalogSnapshot(DomainModel):
    """Production catalog snapshot fetched from production DB for AI context."""
    version: NonEmptyStr
    exam: NonEmptyStr
    subject: NonEmptyStr
    topics: tuple["CatalogTopic", ...]
    subtopics: tuple["CatalogSubtopic", ...]

    @model_validator(mode="after")
    def _check(self) -> "CatalogSnapshot":
        topic_ids = [topic.id for topic in self.topics]
        topic_slugs = [topic.slug for topic in self.topics]
        if len(set(topic_ids)) != len(topic_ids):
            raise ValueError("topic ids must be unique")
        if len(set(topic_slugs)) != len(topic_slugs):
            raise ValueError("topic slugs must be unique")

        subtopic_ids = [subtopic.id for subtopic in self.subtopics]
        subtopic_slugs = [subtopic.slug for subtopic in self.subtopics]
        if len(set(subtopic_ids)) != len(subtopic_ids):
            raise ValueError("subtopic ids must be unique")
        if len(set(subtopic_slugs)) != len(subtopic_slugs):
            raise ValueError("subtopic slugs must be unique")

        known_topics = set(topic_ids)
        for subtopic in self.subtopics:
            if subtopic.topic_id not in known_topics:
                raise ValueError(
                    f"subtopic {subtopic.id!r} points at unknown topic {subtopic.topic_id!r}"
                )
        return self


class VerificationRecord(DomainModel):
    """Embedded verification record (AI or human) carried on the staging row."""
    id: NonEmptyStr
    kind: NonEmptyStr  # "ai" | "human"
    verdict: NonEmptyStr  # "pass" | "fail" | "abstain"
    scope: tuple[NonEmptyStr, ...]
    content_hash: Sha256
    verifier: NonEmptyStr
    detail: NonEmptyStr | None = None
    created_at: AwareDatetime


class Coverage(DomainModel):
    source: NonEmptyStr
    scope: Scope
    item_count: int = 0
    has_more: bool = False


class SourceCapabilities(DomainModel):
    passages: bool = False
    passage_sets: bool = False
    figures: bool = False
    option_figures: bool = False
    rich_text: bool = False
    answer: bool = True
    explanation: bool = False
    sections: bool = False
    marks: bool = False

    def supports(self, capability: str) -> bool:
        return getattr(self, capability, False)


class SourceProfile(DomainModel):
    name: NonEmptyStr
    version: NonEmptyStr
    exams: tuple[NonEmptyStr, ...] = ()
    subjects: dict[NonEmptyStr, NonEmptyStr] = {}
    years: tuple[int, int] | None = None
    capabilities: "SourceCapabilities" = SourceCapabilities()
    rate_limit_per_second: float = Field(default=1.0, gt=0.0)
    health_url: HttpUrl | None = None

    def supports(self, capability: str) -> bool:
        return getattr(self.capabilities, capability, False)


class SourceItem(DomainModel):
    source: NonEmptyStr
    source_url: HttpUrl
    source_item_id: NonEmptyStr
    fetched_at: AwareDatetime
    payload: dict
    payload_hash: Sha256
    scope: Scope
    source_version: NonEmptyStr

    @property
    def external_key(self) -> str:
        return f"{self.source}:{self.source_item_id}"


class MediaRef(DomainModel):
    """Media reference from source (before download)."""
    key: NonEmptyStr
    source_url: HttpUrl
    mime: MimeType | None = None
    alt: NonEmptyStr | None = None
    required: bool = False


class MediaAsset(DomainModel):
    """Downloaded and validated media asset."""
    asset_id: Sha256
    mime: MimeType
    byte_size: int = Field(gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    storage_url: NonEmptyStr
    source_url: HttpUrl | None = None
    fetched_at: AwareDatetime
    required: bool = True
    readable: bool = True


class Mark(DomainModel):
    kind: NonEmptyStr  # bold, italic, underline, strike, subscript, superscript, image
    start: int = Field(ge=0)
    length: int = Field(ge=0)
    asset_id: NonEmptyStr | None = None  # for image marks

    @model_validator(mode="after")
    def _check(self) -> "Mark":
        if self.kind == "image":
            if self.asset_id is None:
                raise ValueError("image marks require an asset_id")
            if self.length != 0:
                raise ValueError("image marks are zero length anchors")
        else:
            if self.asset_id is not None:
                raise ValueError("only image marks may carry an asset_id")
            if self.length < 1:
                raise ValueError("text marks need a positive length")
        return self


class RichText(DomainModel):
    text: NonEmptyStr
    marks: tuple["Mark", ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "RichText":
        last_end = 0
        for mark in self.marks:
            if mark.start < last_end:
                raise ValueError("marks must be sorted and must not overlap")
            end = mark.start + mark.length
            if end > len(self.text):
                raise ValueError("mark extends past the end of the text")
            last_end = end
        return self


class Option(DomainModel):
    id: NonEmptyStr
    text: "RichText"


class Passage(DomainModel):
    id: NonEmptyStr
    text: "RichText"
    source_item_id: NonEmptyStr | None = None


class Content(DomainModel):
    stem: "RichText"
    options: tuple["Option", ...] = Field(min_length=2, max_length=6)
    answer: NonEmptyStr
    marks: PositiveMarks
    passage: Optional["Passage"] = None
    source_explanation: Optional["RichText"] = None
    section: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _check(self) -> "Content":
        option_ids = [option.id for option in self.options]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("option ids must be unique")
        if self.answer not in set(option_ids):
            raise ValueError("answer must name one of the options")
        return self

    def rich_texts(self) -> tuple["RichText", ...]:
        texts: list["RichText"] = [self.stem]
        texts.extend(option.text for option in self.options)
        if self.passage is not None:
            texts.append(self.passage.text)
        if self.source_explanation is not None:
            texts.append(self.source_explanation)
        return tuple(texts)


class Evidence(DomainModel):
    image_descriptions: tuple["DescribeImageResponse", ...] = ()
    tag: Optional["TagProposal"] = None
    explanation: Optional["Explanation"] = None
    answer_verdict: Optional["AnswerVerdict"] = None
    gate: Optional["GateVerdict"] = None
    verifications: tuple[Any, ...] = ()

    @model_validator(mode="after")
    def _check_verifications(self) -> "Evidence":
        from .proposals import TagProposal, Explanation, AnswerVerdict
        from .validation import GateVerdict, Verification
        for v in self.verifications:
            if not isinstance(v, (VerificationRecord, Verification)):
                raise ValueError("verification must be VerificationRecord or Verification")
        return self


class StagingItem(DomainModel):
    """
    Single staging row - the complete work unit.
    This is the ONE table in our staging DB.
    """
    id: NonEmptyStr  # same as provenance.external_key
    provenance: "Provenance"
    content: "Content"
    media_refs: tuple["MediaRef", ...] = ()
    media_assets: tuple["MediaAsset", ...] = ()
    evidence: Any = Field(default_factory=lambda: Evidence())
    catalog: Optional["CatalogRef"] = None
    state: NonEmptyStr = "acquired"  # acquired, adapted, gated, media_ready, described, enriched, verified, ready
    hashes: Optional["Hashes"] = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    attempts: int = 0
    error: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _check_evidence(self) -> "StagingItem":
        if self.evidence.__class__.__name__ != "Evidence":
            raise ValueError("evidence must be an Evidence instance")
        return self

    @model_validator(mode="after")
    def _check_catalog_scope(self) -> "StagingItem":
        if self.catalog is not None:
            scope = self.provenance.scope
            expected = (scope.exam, scope.subject, scope.year, scope.section)
            actual = (self.catalog.exam, self.catalog.subject, self.catalog.year, self.catalog.section)
            if actual != expected:
                raise ValueError("catalog must match the provenance scope")
        return self

    @model_validator(mode="after")
    def _check_media(self) -> "StagingItem":
        media_keys = {ref.key for ref in self.media_refs}
        asset_ids = {asset.asset_id for asset in self.media_assets}
        known_media = media_keys | asset_ids

        for rich_text in self.content.rich_texts():
            for mark in rich_text.marks:
                if mark.kind == "image" and mark.asset_id not in known_media:
                    raise ValueError(f"mark references unknown media {mark.asset_id!r}")

        for description in self.evidence.image_descriptions:
            if description.asset_id not in known_media:
                raise ValueError(f"description references unknown media {description.asset_id!r}")

        return self

    @model_validator(mode="after")
    def _check_verification_hashes(self) -> "StagingItem":
        if self.hashes is None:
            return self
        for record in self.evidence.verifications:
            if record.content_hash != self.hashes.content_hash:
                raise ValueError(
                    "verification content hash does not match this bundle content hash"
                )
        return self


# Capability request/response models
class DescribeImageRequest(DomainModel):
    asset: "MediaAsset"
    context: NonEmptyStr | None = None


class ExplainRequest(DomainModel):
    """Explain request WITH catalog context for AI to reference syllabus."""
    item: "StagingItem"
    catalog: Optional["CatalogSnapshot"] = None


class TagRequest(DomainModel):
    item: "StagingItem"
    catalog: Any = None


class VerifyAnswerRequest(DomainModel):
    item: "StagingItem"
    catalog: Any = None


class DescribeImageResponse(DomainModel):
    asset_id: Sha256
    description: NonEmptyStr
    facts: tuple[NonEmptyStr, ...] = ()
    confidence: Confidence
    producer: "Producer"
    contributors: tuple["Producer", ...] = ()


class ExplainResponse(DomainModel):
    key_point: "RichText"
    body: "RichText"
    trap: Optional["RichText"] = None
    confidence: Confidence
    producer: "Producer"


class TagResponse(DomainModel):
    topic_id: NonEmptyStr
    subtopic_id: NonEmptyStr
    evidence: NonEmptyStr
    confidence: Confidence
    producer: "Producer"


class VerifyAnswerResponse(DomainModel):
    verdict: NonEmptyStr  # pass | fail | abstain
    reasoning: NonEmptyStr
    confidence: Confidence
    producer: "Producer"


# Import forward-referenced types for model_rebuild
from .proposals import (
    TagProposal,
    Explanation,
    AnswerVerdict,
    ImageDescription,
)
from .validation import GateVerdict

# Resolve forward references for models with forward references
CatalogRef.model_rebuild()
StagingItem.model_rebuild()
Evidence.model_rebuild()
ExplainRequest.model_rebuild()
TagRequest.model_rebuild()
VerifyAnswerRequest.model_rebuild()
DescribeImageRequest.model_rebuild()
DescribeImageResponse.model_rebuild()
ExplainResponse.model_rebuild()
TagResponse.model_rebuild()
VerifyAnswerResponse.model_rebuild()