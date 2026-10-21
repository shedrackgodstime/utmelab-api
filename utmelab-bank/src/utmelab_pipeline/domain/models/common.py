"""Shared value objects and constrained types."""

from datetime import UTC, datetime
from typing import Annotated, Any, Optional, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

from ..enums import (
    ImagePosition,
    MarkKind,
    Severity,
    SourceCapability,
    State,
    VerificationKind,
    Verdict,
)

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
#: Content text, preserved exactly as it arrived.
#:
#: Unlike `NonEmptyStr` this does not strip whitespace, and it must not.
#: Production stores some explanation bodies and key points with a leading
#: space, and the content fingerprint hashes those bytes verbatim. Stripping
#: them changes the hash, so a stripped row can never match a production row.
Text = Annotated[str, StringConstraints(min_length=1)]
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
    """Base for canonical values. Unknown fields are rejected on purpose.

    ``str_strip_whitespace`` is deliberately off. A model wide strip would
    rewrite the text of every content field, and production stores some
    explanation bodies and key points with a leading space. The fingerprint
    hashes those bytes, so a stripped row can never match a production row.
    Identifiers still get stripped, because the types that carry them say so.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
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

class Clearance(DomainModel):
    """A person clearing one judgement issue, with the reason recorded.

    The escape hatch for the rules a machine cannot settle. A clearance is
    never silent: it names the rule, the person and the reason, so the
    decision survives the row.
    """

    rule: NonEmptyStr
    by: NonEmptyStr
    reason: NonEmptyStr
    created_at: AwareDatetime


class GateVerdict(DomainModel):
    """The mechanical gate decision. Passing is not a warning free pass.

    A row passes when no error issue is open and every judgement issue has
    been cleared by a person. A warning never blocks, and the gate does not
    raise one for a rule.
    """

    passed: bool
    issues: tuple[Issue, ...] = ()
    clearances: tuple[Clearance, ...] = ()
    rules_version: NonEmptyStr = "v1"

    @model_validator(mode="after")
    def _check(self) -> "GateVerdict":
        has_error = any(issue.severity is Severity.ERROR for issue in self.issues)
        cleared = {clearance.rule for clearance in self.clearances}
        open_judgement = any(
            issue.severity is Severity.JUDGEMENT and issue.code not in cleared
            for issue in self.issues
        )
        if self.passed == (has_error or open_judgement):
            raise ValueError(
                "passed must be true exactly when no error is open and every "
                "judgement issue is cleared"
            )
        return self


class Verification(DomainModel):
    """A verification record carried on the staging row.

    The trust rule lives here: an AI verification must name the model that
    produced it, and a human verification must not carry a model producer.
    """
    id: NonEmptyStr
    kind: VerificationKind
    verdict: Verdict
    scope: tuple[NonEmptyStr, ...] = Field(min_length=1)
    content_hash: Sha256
    reviewer: NonEmptyStr
    note: NonEmptyStr | None = None
    created_at: AwareDatetime
    producer: Optional[Producer] = None

    @model_validator(mode="after")
    def _check(self) -> "Verification":
        if self.kind is VerificationKind.AI and self.producer is None:
            raise ValueError("AI verification requires a producer")
        if self.kind is VerificationKind.HUMAN and self.producer is not None:
            raise ValueError("human verification cannot carry a model producer")
        return self


class Coverage(DomainModel):
    source: Slug
    scope: Scope
    item_count: int = Field(ge=0)
    has_more: bool = False
    notes: NonEmptyStr | None = None


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

    def supports(self, capability: "SourceCapability") -> bool:
        return bool(getattr(self, capability.value, False))


class SourceProfile(DomainModel):
    name: Slug
    version: NonEmptyStr
    exams: tuple[NonEmptyStr, ...] = Field(min_length=1)
    subjects: dict[NonEmptyStr, NonEmptyStr] = Field(min_length=1)
    years: tuple[Year, Year] | None = None
    capabilities: "SourceCapabilities" = SourceCapabilities()
    rate_limit_per_second: float = Field(default=1.0, gt=0.0)
    health_url: HttpUrl | None = None

    @model_validator(mode="after")
    def _check(self) -> "SourceProfile":
        if len(set(self.exams)) != len(self.exams):
            raise ValueError("exams must be unique")
        if self.years is not None and self.years[0] > self.years[1]:
            raise ValueError("years must be ordered low to high")
        return self

    def supports(self, capability: "SourceCapability") -> bool:
        return self.capabilities.supports(capability)


class SourceItem(DomainModel):
    source: Slug
    source_url: HttpUrl
    source_item_id: NonEmptyStr
    fetched_at: AwareDatetime
    payload: dict[str, Any]
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
    """One mark on a piece of text.

    The shape is the production shape: offsets in Unicode characters, and a
    flat kind. An image mark is an anchor, so its length is zero, and it
    carries a url and a position rather than a hash.
    """

    kind: MarkKind
    start: int = Field(ge=0)
    len: int = Field(ge=0)
    #: The url, as a raw string. Production stores it verbatim and the
    #: fingerprint hashes it verbatim, so a normalising url type would change
    #: the hash. `https://example.com` and `https://example.com/` are
    #: different rows.
    url: Optional[str] = None
    position: Optional[ImagePosition] = None
    alt: Optional[NonEmptyStr] = None

    @model_validator(mode="after")
    def _check(self) -> "Mark":
        if self.kind is MarkKind.IMAGE:
            if self.url is None:
                raise ValueError("image marks require a url")
            if not self.url.startswith("https://"):
                raise ValueError("image urls must be absolute https")
            if self.position is None:
                raise ValueError("image marks require a position")
            if self.len != 0:
                raise ValueError("image marks are zero length anchors")
        else:
            if self.url is not None or self.position is not None or self.alt is not None:
                raise ValueError("only image marks may carry a url, position or alt")
            if self.len < 1:
                raise ValueError("text marks need a positive length")
        return self


class RichText(DomainModel):
    text: Text
    marks: tuple["Mark", ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "RichText":
        """The load rules production applies, mirrored.

        ``RichText::validate`` in ``utmelab-api-old/src/bank/model.rs``: a mark
        running past the end of the text is refused, a mark that partially
        overlaps another is refused, and two marks may share an identical
        range. Bold on top of underline is the case that makes the last rule
        matter.
        """
        n = len(self.text)
        for i, mark in enumerate(self.marks):
            if mark.start + mark.len > n:
                raise ValueError(
                    f"mark {i} (start {mark.start}, len {mark.len}) runs past "
                    f"the end of {n} characters"
                )
        # Sorted by (start, len), any overlapping set has an overlapping
        # adjacent pair. Identical ranges are allowed.
        order = sorted(
            range(len(self.marks)),
            key=lambda i: (self.marks[i].start, self.marks[i].len),
        )
        for a, b in zip(order, order[1:]):
            first, second = self.marks[a], self.marks[b]
            identical = (
                second.start == first.start and second.len == first.len
            )
            if second.start < first.start + first.len and not identical:
                raise ValueError(
                    f"mark (start {second.start}, len {second.len}) partially "
                    f"overlaps (start {first.start}, len {first.len})"
                )
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
    image_descriptions: tuple["ImageDescription", ...] = ()
    tag: Optional["TagProposal"] = None
    explanation: Optional["Explanation"] = None
    answer_verdict: Optional["AnswerVerdict"] = None
    gate: Optional["GateVerdict"] = None
    verifications: tuple["Verification", ...] = ()


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
    evidence: "Evidence" = Field(default_factory=lambda: Evidence())
    catalog: Optional["CatalogRef"] = None
    state: "State" = State.ACQUIRED
    hashes: Optional["Hashes"] = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    attempts: int = 0
    error: NonEmptyStr | None = None

    def transition_to(self, target: "State", *, error: NonEmptyStr | None = None) -> "StagingItem":
        """Move to a new state. The state machine refuses an invented move.

        Staying put is not a move. Re-running a stage on an item that already
        reached it is idempotent, so it updates the record without asking the
        state machine for permission.
        """
        from ..state import assert_transition

        resolved = State(target)
        if self.state is not resolved:
            assert_transition(self.state, resolved)
        return self.model_copy(
            update={
                "state": resolved,
                "error": error,
                "updated_at": datetime.now(UTC),
            }
        )

    def with_content_hash(self) -> "StagingItem":
        """Stamp the content hash that a verification is written against."""
        from ..hashing import content_fingerprint

        fingerprint = content_fingerprint(
            stem=self.content.stem,
            options=self.content.options,
            answer=self.content.answer,
            explanation=self.evidence.explanation,
        )
        if self.hashes is None:
            raise ValueError("cannot stamp a content hash before the payload hash is known")
        return self.model_copy(
            update={
                "hashes": self.hashes.model_copy(update={"content_hash": fingerprint}),
                "updated_at": datetime.now(UTC),
            }
        )

    @model_validator(mode="after")
    def _check_identity(self) -> "StagingItem":
        if self.id != self.provenance.external_key:
            raise ValueError("id must be source:source_item_id")
        return self

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
                if mark.kind is MarkKind.IMAGE and mark.url is None:
                    raise ValueError("image mark has no url")

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

# Resolve forward references for models with forward references
CatalogRef.model_rebuild()
StagingItem.model_rebuild()
Evidence.model_rebuild()
ExplainRequest.model_rebuild()
TagRequest.model_rebuild()
VerifyAnswerRequest.model_rebuild()
DescribeImageRequest.model_rebuild()
ExplainResponse.model_rebuild()
TagResponse.model_rebuild()
VerifyAnswerResponse.model_rebuild()