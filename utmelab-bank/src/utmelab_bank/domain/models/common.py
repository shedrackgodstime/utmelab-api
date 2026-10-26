"""Shared value objects and constrained types."""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

from ..enums import (
    ImagePosition,
    InlineKind,
    PassageKind,
    Severity,
    SourceCapability,
    State,
    Verdict,
    VerificationKind,
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
CountryCode = Annotated[
    str,
    StringConstraints(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Za-z]{2}$",
        strip_whitespace=True,
    ),
]


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
    country: CountryCode | None = None

    @field_validator("country")
    @classmethod
    def _normalise_country(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


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
    countries: tuple[CountryCode, ...] = ()


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
    topics: tuple[CatalogTopic, ...]
    subtopics: tuple[CatalogSubtopic, ...]
    country: CountryCode | None = None

    @model_validator(mode="after")
    def _check(self) -> CatalogSnapshot:
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
    """A person resolving one refusal, with the reason recorded.

    The escape hatch for the gate. A clearance is never silent: it names the
    rule, the person and the reason, so the decision survives the row and the
    counts still say what was resolved and how.
    """

    rule: NonEmptyStr
    by: NonEmptyStr
    reason: NonEmptyStr
    created_at: AwareDatetime


class GateVerdict(DomainModel):
    """The mechanical gate decision. Passing is not a warning free pass.

    Every refusal goes to a person. A row passes when every issue it raised
    has been cleared, and it passes with no issues at all.

    The severity on an issue says what kind of refusal it was. A defect is
    objective and the normal resolution is a fix to the content. A judgement
    is a case the machine cannot settle. Both are cleared the same way,
    because both need a person, and the severity keeps the two apart in the
    counts.
    """

    passed: bool
    issues: tuple[Issue, ...] = ()
    clearances: tuple[Clearance, ...] = ()
    rules_version: NonEmptyStr = "v1"

    @property
    def unresolved(self) -> tuple[Issue, ...]:
        """The issues no clearance has answered yet. The human's queue."""
        cleared = {clearance.rule for clearance in self.clearances}
        return tuple(issue for issue in self.issues if issue.code not in cleared)

    @model_validator(mode="after")
    def _check(self) -> GateVerdict:
        if self.passed == bool(self.unresolved):
            raise ValueError("passed must be true exactly when every issue has been cleared")
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
    producer: Producer | None = None

    @model_validator(mode="after")
    def _check(self) -> Verification:
        """The trust rule.

        A machine check must name the machine that made it, so the evidence
        can be traced and the agreement rate can be computed per model. A
        human check must not carry a model producer, because a person is not
        a model and a row that says otherwise is not evidence of anything.
        """
        if self.kind is VerificationKind.HUMAN:
            if self.producer is not None:
                raise ValueError("human verification cannot carry a model producer")
        elif self.producer is None:
            raise ValueError(f"{self.kind.value} verification requires a producer")
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

    def supports(self, capability: SourceCapability) -> bool:
        return bool(getattr(self, capability.value, False))


class SourceProfile(DomainModel):
    name: Slug
    version: NonEmptyStr
    exams: tuple[NonEmptyStr, ...] = Field(min_length=1)
    subjects: dict[NonEmptyStr, NonEmptyStr] = Field(min_length=1)
    years: tuple[Year, Year] | None = None
    capabilities: SourceCapabilities = SourceCapabilities()
    rate_limit_per_second: float = Field(default=1.0, gt=0.0)
    health_url: HttpUrl | None = None

    @model_validator(mode="after")
    def _check(self) -> SourceProfile:
        if len(set(self.exams)) != len(self.exams):
            raise ValueError("exams must be unique")
        if self.years is not None and self.years[0] > self.years[1]:
            raise ValueError("years must be ordered low to high")
        return self

    def supports(self, capability: SourceCapability) -> bool:
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
    #: Decoded base64 image blobs from data: URLs, keyed by media ref key.
    #: Populated by the source adapter when the source embeds images as data URLs.
    media_blobs: dict[str, bytes] = {}

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
    #: The bare name the bank records, ``<sha>.<ext>``. The host is config,
    #: not data, so a move is a base change and not a migration.
    storage_url: NonEmptyStr
    source_url: HttpUrl | None = None
    fetched_at: AwareDatetime
    required: bool = True
    readable: bool = True


class OcrWord(DomainModel):
    """One OCR word and its pixel bounds in the source image."""

    text: NonEmptyStr
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)


class OcrRecord(DomainModel):
    """OCR enrichment for one captured asset, including a durable failure."""

    asset_id: Sha256
    producer: Producer
    text: str = ""
    words: tuple[OcrWord, ...] = ()
    error: NonEmptyStr | None = None


class MediaCheck(DomainModel):
    """Deterministic validation recorded for one captured asset."""

    asset_id: Sha256
    status: NonEmptyStr
    mime: MimeType
    detected_mime: MimeType | None = None
    byte_size: int = Field(ge=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    ocr_status: NonEmptyStr
    issues: tuple[NonEmptyStr, ...] = ()


class Inline(DomainModel):
    """One inline on a piece of text.

    The shape is the production shape: offsets in Unicode characters, and a
    flat kind. An image inline is an anchor, so its length is zero, and it
    carries a value and a position rather than a hash.

    For an image, ``url`` holds the source url before capture and the bare
    stored name (``<sha>.<ext>``) after. The serving layer composes the public
    url, so the host is configuration and not content.
    """

    kind: InlineKind
    start: int = Field(ge=0)
    len: int = Field(ge=0)
    #: The source url before capture, the stored name after. Kept as a raw
    #: string because production stores it verbatim and the fingerprint
    #: hashes it verbatim.
    url: str | None = None
    position: ImagePosition | None = None
    alt: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _check(self) -> Inline:
        if self.kind is InlineKind.IMAGE:
            if not self.url:
                raise ValueError("image inline require a source url or a stored name")
            if self.position is None:
                raise ValueError("image inline require a position")
            if self.len != 0:
                raise ValueError("image inline are zero length anchors")
        else:
            if self.url is not None or self.position is not None or self.alt is not None:
                raise ValueError("only image inline may carry a url, position or alt")
            if self.len < 1:
                raise ValueError("text inline need a positive length")
        return self


class RichText(DomainModel):
    text: Text
    inline: tuple[Inline, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> RichText:
        """The load rules production applies, mirrored.

        ``RichText::validate`` in ``utmelab-api-old/src/bank/model.rs``: an inline
        running past the end of the text is refused, one that partially
        overlaps another is refused, and two inlines may share an identical
        range. Bold on top of underline is the case that makes the last rule
        matter.
        """
        n = len(self.text)
        for i, inline in enumerate(self.inline):
            if inline.start + inline.len > n:
                raise ValueError(
                    f"inline {i} (start {inline.start}, len {inline.len}) runs past "
                    f"the end of {n} characters"
                )
        # Sorted by (start, len), any overlapping set has an overlapping
        # adjacent pair. Identical ranges are allowed.
        order = sorted(
            range(len(self.inline)),
            key=lambda i: (self.inline[i].start, self.inline[i].len),
        )
        for a, b in zip(order, order[1:], strict=False):
            first, second = self.inline[a], self.inline[b]
            identical = second.start == first.start and second.len == first.len
            if second.start < first.start + first.len and not identical:
                raise ValueError(
                    f"inline (start {second.start}, len {second.len}) partially "
                    f"overlaps (start {first.start}, len {first.len})"
                )
        return self


class Option(DomainModel):
    id: NonEmptyStr
    text: RichText


class Passage(DomainModel):
    """A stimulus shared by many questions.

    The production shape, column for column, because a passage is a row in
    the served tables and not a fragment inside a question. Production has 8
    of these and 28 questions point at one, so a passage that lives inside a
    question cannot be shared and has nowhere to put its kind.
    """

    id: NonEmptyStr
    exam: NonEmptyStr
    subject: NonEmptyStr
    year: Year
    kind: PassageKind
    title: NonEmptyStr | None = None
    author: NonEmptyStr | None = None
    text: RichText
    source_item_id: NonEmptyStr | None = None


class Content(DomainModel):
    stem: RichText
    options: tuple[Option, ...] = Field(min_length=2, max_length=6)
    answer: NonEmptyStr
    #: What the question is worth. The mark value, not the inline list, so
    #: the two never share a name: production has a `marks` column and an
    #: `inline` column, and so does this.
    marks: PositiveMarks
    #: The id of the passage this question needs, or null. A reference, not
    #: the passage itself: production has 28 questions pointing at 8
    #: passages, and only a reference lets two questions share one.
    passage_id: NonEmptyStr | None = None
    source_explanation: RichText | None = None
    section: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _check(self) -> Content:
        option_ids = [option.id for option in self.options]
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("option ids must be unique")
        if self.answer not in set(option_ids):
            raise ValueError("answer must name one of the options")
        return self

    def rich_texts(self) -> tuple[RichText, ...]:
        texts: list[RichText] = [self.stem]
        texts.extend(option.text for option in self.options)
        if self.source_explanation is not None:
            texts.append(self.source_explanation)
        return tuple(texts)


class Evidence(DomainModel):
    media_checks: tuple[MediaCheck, ...] = ()
    ocr: tuple[OcrRecord, ...] = ()
    image_descriptions: tuple[ImageDescription, ...] = ()
    tag: TagProposal | None = None
    explanation: Explanation | None = None
    answer_verdict: AnswerVerdict | None = None
    gate: GateVerdict | None = None
    verifications: tuple[Verification, ...] = ()


class StagingItem(DomainModel):
    """
    Single staging row - the complete work unit.
    This is the ONE table in our staging DB.
    """

    id: NonEmptyStr  # same as provenance.external_key
    provenance: Provenance
    content: Content
    #: The passage this item introduces, if it brings one. The content names
    #: it by id, and several questions can name the same one.
    passage: Passage | None = None
    media_refs: tuple[MediaRef, ...] = ()
    media_assets: tuple[MediaAsset, ...] = ()
    #: Decoded base64 image blobs from data: URLs, keyed by media ref key.
    #: Populated by the source adapter and used by capture_refs.
    media_blobs: dict[str, bytes] = {}
    evidence: Evidence = Field(default_factory=lambda: Evidence())
    catalog: CatalogRef | None = None
    state: State = State.ACQUIRED
    hashes: Hashes | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    attempts: int = 0
    error: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _check(self) -> StagingItem:
        """The passage the content names must be the passage the item carries.

        A reference to a passage the item does not carry is fine, because the
        passage may already be held. A reference to a passage the item does
        carry under a different id is not.
        """
        if (
            self.passage is not None
            and self.content.passage_id is not None
            and self.passage.id != self.content.passage_id
        ):
            raise ValueError(
                "the content names passage "
                f"{self.content.passage_id!r} but the item carries "
                f"{self.passage.id!r}"
            )
        return self

    def transition_to(self, target: State, *, error: NonEmptyStr | None = None) -> StagingItem:
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

    def stamp_hashes(self) -> StagingItem:
        """Build the row's hashes from the row itself.

        This is the one producer. ``payload_hash`` comes from the source
        payload the row records, ``content_hash`` is production's content
        fingerprint, and ``bundle_hash`` is the bank's wider fingerprint that
        also covers the passage, the section and the media.

        Run it again after any edit to the content, the passage or the media,
        so the hash a verification is written against is the hash of the row
        as it stands.
        """
        from ..hashing import bundle_fingerprint, content_fingerprint

        content_hash = content_fingerprint(
            stem=self.content.stem,
            options=self.content.options,
            answer=self.content.answer,
            explanation=self.evidence.explanation,
        )
        passage = self.passage
        bundle_hash = bundle_fingerprint(
            content_hash=content_hash,
            passage_id=passage.id if passage is not None else self.content.passage_id,
            passage_text=passage.text.text if passage is not None else "",
            passage_inline=passage.text.inline if passage is not None else (),
            section=self.content.section or self.provenance.scope.section,
            media_ids=tuple(asset.asset_id for asset in self.media_assets),
        )
        hashes = Hashes(
            payload_hash=self.provenance.payload_hash,
            content_hash=content_hash,
            bundle_hash=bundle_hash,
        )
        return self.model_copy(
            update={"hashes": hashes, "updated_at": datetime.now(UTC)},
        )

    def with_content_hash(self) -> StagingItem:
        """Stamp the content hash that a verification is written against."""
        return self.stamp_hashes()

    @model_validator(mode="after")
    def _check_identity(self) -> StagingItem:
        if self.id != self.provenance.external_key:
            raise ValueError("id must be source:source_item_id")
        return self

    @model_validator(mode="after")
    def _check_evidence(self) -> StagingItem:
        if self.evidence.__class__.__name__ != "Evidence":
            raise ValueError("evidence must be an Evidence instance")
        return self

    @model_validator(mode="after")
    def _check_catalog_scope(self) -> StagingItem:
        if self.catalog is not None:
            scope = self.provenance.scope
            expected = (scope.exam, scope.subject, scope.year, scope.section)
            actual = (
                self.catalog.exam,
                self.catalog.subject,
                self.catalog.year,
                self.catalog.section,
            )
            if actual != expected:
                raise ValueError("catalog must match the provenance scope")
        return self

    @model_validator(mode="after")
    def _check_media(self) -> StagingItem:
        media_keys = {ref.key for ref in self.media_refs}
        asset_ids = {asset.asset_id for asset in self.media_assets}
        known_media = media_keys | asset_ids

        for rich_text in self.content.rich_texts():
            for inline in rich_text.inline:
                if inline.kind is InlineKind.IMAGE and inline.url is None:
                    raise ValueError("image inline has no url")

        for description in self.evidence.image_descriptions:
            if description.asset_id not in known_media:
                raise ValueError(f"description references unknown media {description.asset_id!r}")

        return self

    @model_validator(mode="after")
    def _check_verification_hashes(self) -> StagingItem:
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
    asset: MediaAsset
    context: NonEmptyStr | None = None
    #: The downloaded bytes, when the caller holds them. The served url is a
    #: remote address, so an adapter that needs a local file must be handed
    #: the bytes rather than asked to reconstruct a path from the url.
    data: bytes | None = None


class ExplainRequest(DomainModel):
    """Explain request WITH catalog context for AI to reference syllabus."""

    item: StagingItem
    catalog: CatalogSnapshot | None = None


class TagRequest(DomainModel):
    item: StagingItem
    catalog: Any = None


class VerifyAnswerRequest(DomainModel):
    item: StagingItem
    catalog: Any = None


class ExplainResponse(DomainModel):
    key_point: RichText
    body: RichText
    trap: RichText | None = None
    confidence: Confidence
    producer: Producer


class TagResponse(DomainModel):
    topic_id: NonEmptyStr
    subtopic_id: NonEmptyStr
    evidence: NonEmptyStr
    confidence: Confidence
    producer: Producer


class VerifyAnswerResponse(DomainModel):
    verdict: NonEmptyStr  # pass | fail | abstain
    reasoning: NonEmptyStr
    confidence: Confidence
    producer: Producer


# Import forward-referenced types for model_rebuild. The import stays here
# because proposals imports common, so a module-level import above would be
# circular. It also puts the names in this module's globals, which is what
# model_rebuild() resolves against.
from .proposals import (  # noqa: E402
    AnswerVerdict,
    Explanation,
    ImageDescription,
    TagProposal,
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
