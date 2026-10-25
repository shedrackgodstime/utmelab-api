"""Canonical models. Import from here, not from individual modules.

Every model is defined once, in exactly one module. This package re-exports
them so callers have a single import path, and there is never a second class
object with the same name.
"""

from pydantic import BaseModel

from .catalog import CatalogRef, CatalogSnapshot, CatalogSubtopic, CatalogTopic
from .common import (
    Clearance,
    Confidence,
    Content,
    Coverage,
    DescribeImageRequest,
    DomainModel,
    Evidence,
    ExplainRequest,
    ExplainResponse,
    GateVerdict,
    Hashes,
    Inline,
    Issue,
    MediaAsset,
    MediaRef,
    MimeType,
    NonEmptyStr,
    OcrRecord,
    OcrWord,
    Option,
    Passage,
    PositiveMarks,
    Producer,
    Provenance,
    RichText,
    Scope,
    Sha256,
    Slug,
    SourceCapabilities,
    SourceItem,
    SourceProfile,
    StagingItem,
    TagRequest,
    TagResponse,
    Verification,
    VerifyAnswerRequest,
    VerifyAnswerResponse,
    Year,
)
from .proposals import (
    AnswerVerdict,
    Explanation,
    ImageDescription,
    TagProposal,
)

PAYLOAD_HASH = "b" * 64
CONTENT_HASH = "c" * 64
BUNDLE_HASH = "d" * 64


def rebuild(model: BaseModel, **updates: object) -> BaseModel:
    """Rebuild a model with updated fields, using JSON serialization for proper validation."""
    if not hasattr(model, "model_dump"):
        raise TypeError(f"model must have a model_dump method, got {type(model)}")
    data = model.model_dump(mode="json")
    data.update(updates)
    return type(model).model_validate(data)


__all__ = [
    "AnswerVerdict",
    "BUNDLE_HASH",
    "CONTENT_HASH",
    "CatalogRef",
    "CatalogSnapshot",
    "CatalogSubtopic",
    "CatalogTopic",
    "Clearance",
    "Confidence",
    "Content",
    "Coverage",
    "DescribeImageRequest",
    "DomainModel",
    "Evidence",
    "ExplainRequest",
    "ExplainResponse",
    "Explanation",
    "GateVerdict",
    "Hashes",
    "ImageDescription",
    "Inline",
    "Issue",
    "MediaAsset",
    "MediaRef",
    "MimeType",
    "NonEmptyStr",
    "Option",
    "OcrRecord",
    "OcrWord",
    "PAYLOAD_HASH",
    "Passage",
    "PositiveMarks",
    "Producer",
    "Provenance",
    "RichText",
    "Scope",
    "Sha256",
    "Slug",
    "SourceCapabilities",
    "SourceItem",
    "SourceProfile",
    "StagingItem",
    "TagProposal",
    "TagRequest",
    "TagResponse",
    "Verification",
    "VerifyAnswerRequest",
    "VerifyAnswerResponse",
    "Year",
    "rebuild",
]
