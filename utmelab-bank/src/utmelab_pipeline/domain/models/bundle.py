"""The bundle is the unit of promotion."""

from pydantic import AwareDatetime, Field, model_validator

from ..enums import MarkKind, State
from .catalog import CatalogRef
from .common import DomainModel, Hashes, NonEmptyStr, Provenance
from .content import MediaRef
from .common import Content
from .proposals import AnswerVerdict, Explanation, ImageDescription, TagProposal
from .validation import GateVerdict, Verification


def _check_identity(
    bundle_id: str,
    provenance: Provenance,
    catalog: CatalogRef | None,
) -> None:
    if bundle_id != provenance.external_key:
        raise ValueError("bundle_id must be source:source_item_id")
    if catalog is None:
        return
    scope = provenance.scope
    expected = (scope.exam, scope.subject, scope.year, scope.section)
    actual = (catalog.exam, catalog.subject, catalog.year, catalog.section)
    if actual != expected:
        raise ValueError("catalog must match the provenance scope")


def _check_passage(content: Content, provenance: Provenance) -> None:
    passage = content.passage
    if (
        passage is not None
        and passage.source_item_id is not None
        and passage.source_item_id != provenance.source_item_id
    ):
        raise ValueError("passage source_item_id must match provenance")


class Evidence(DomainModel):
    image_descriptions: tuple[ImageDescription, ...] = ()
    tag: TagProposal | None = None
    explanation: Explanation | None = None
    answer_verdict: AnswerVerdict | None = None
    gate: GateVerdict | None = None
    verifications: tuple[Verification, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "Evidence":
        asset_ids = [item.asset_id for item in self.image_descriptions]
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("one image description per asset")
        return self


class BundleState(DomainModel):
    state: State
    attempts: int = Field(default=0, ge=0)
    last_error: NonEmptyStr | None = None
    updated_at: AwareDatetime | None = None


class RawBundle(DomainModel):
    """The adapted bundle before media is fetched and evidence is attached."""

    bundle_id: NonEmptyStr
    provenance: Provenance
    catalog: CatalogRef
    content: Content
    media: tuple[MediaRef, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "RawBundle":
        _check_identity(self.bundle_id, self.provenance, self.catalog)

        media_keys = [ref.key for ref in self.media]
        if len(set(media_keys)) != len(media_keys):
            raise ValueError("media keys must be unique")
        known_media = set(media_keys)

        for rich_text in self.content.rich_texts():
            for mark in rich_text.marks:
                if mark.kind is MarkKind.IMAGE and mark.asset_id not in known_media:
                    raise ValueError(f"mark references unknown media key {mark.asset_id!r}")

        _check_passage(self.content, self.provenance)
        return self


class Bundle(DomainModel):
    bundle_id: NonEmptyStr
    provenance: Provenance
    catalog: CatalogRef | None
    content: Content
    media: tuple[MediaAsset, ...] = ()
    evidence: Evidence = Field(default_factory=Evidence)
    state: BundleState
    hashes: Hashes

    @model_validator(mode="after")
    def _check(self) -> "Bundle":
        _check_identity(self.bundle_id, self.provenance, self.catalog)

        media_ids = [asset.asset_id for asset in self.media]
        if len(set(media_ids)) != len(media_ids):
            raise ValueError("media assets must be unique")
        known_media = set(media_ids)

        for rich_text in self.content.rich_texts():
            for mark in rich_text.marks:
                if mark.kind is MarkKind.IMAGE and mark.asset_id not in known_media:
                    raise ValueError(f"mark references unknown asset {mark.asset_id!r}")

        for description in self.evidence.image_descriptions:
            if description.asset_id not in known_media:
                raise ValueError(
                    f"description references unknown asset {description.asset_id!r}"
                )

        for verification in self.evidence.verifications:
            if verification.content_hash != self.hashes.content_hash:
                raise ValueError("verification must target this content hash")

        _check_passage(self.content, self.provenance)
        return self
