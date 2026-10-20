"""Canonical models. Import from here, not from individual modules."""

from .bundle import Bundle, BundleState, Evidence, RawBundle
from .catalog import CatalogRef, CatalogSnapshot, CatalogSubtopic, CatalogTopic
from .common import (
    Confidence,
    DomainModel,
    Hashes,
    Issue,
    Mark,
    MediaAsset,
    MediaRef,
    MimeType,
    NonEmptyStr,
    Option,
    Passage,
    PositiveMarks,
    Producer,
    Provenance,
    RichText,
    Scope,
    Sha256,
    Slug,
    StagingItem,
    Year,
    Content,
    VerificationRecord,
)
from .content import MediaRef
from .proposals import AnswerVerdict, Explanation, ImageDescription, TagProposal, DescribeImageResponse
from .source import (
    Coverage,
    SourceCapabilities,
    SourceItem,
    SourceProfile,
)
from .validation import GateVerdict, Verification


def rebuild(model, **updates):
    """Rebuild a model with updated fields, using JSON serialization for proper validation."""
    print(f"DEBUG rebuild: model type={type(model)}, has model_dump={hasattr(model, 'model_dump')}")
    if not hasattr(model, "model_dump"):
        raise TypeError(f"model must have a model_dump method (Pydantic model), got {type(model)}")
    data = model.model_dump(mode="json")
    data.update(updates)
    return type(model).model_validate(data)

__all__ = [
    "AnswerVerdict",
    "Bundle",
    "BundleState",
    "CatalogRef",
    "CatalogSnapshot",
    "CatalogSubtopic",
    "CatalogTopic",
    "Confidence",
    "Content",
    "Coverage",
    "DomainModel",
    "Evidence",
    "Explanation",
    "GateVerdict",
    "Hashes",
    "ImageDescription",
    "Issue",
    "Mark",
    "MediaAsset",
    "MediaRef",
    "MimeType",
    "NonEmptyStr",
    "Option",
    "Passage",
    "PositiveMarks",
    "Producer",
    "Provenance",
    "RawBundle",
    "RichText",
    "Scope",
    "Sha256",
    "Slug",
    "StagingItem",
    "SourceCapabilities",
    "SourceItem",
    "SourceProfile",
    "TagProposal",
    "Verification",
    "VerificationRecord",
    "DescribeImageResponse",
    "Year",
]