"""Capability names and their typed request models."""

from pydantic import BaseModel

from .models import (
    CatalogSnapshot,
    DescribeImageRequest,
    ExplainRequest,
    ImageDescription,
    MediaAsset,
    TagRequest,
    VerifyAnswerRequest,
)
from .models.common import (
    ExplainResponse,
    TagResponse,
    VerifyAnswerResponse,
)


CAPABILITY_INPUTS: dict[str, type[BaseModel]] = {
    "describe_image": DescribeImageRequest,
    "explain": ExplainRequest,
    "tag": TagRequest,
    "verify_answer": VerifyAnswerRequest,
}

CAPABILITY_OUTPUTS: dict[str, type[BaseModel]] = {
    "describe_image": ImageDescription,
    "explain": ExplainResponse,
    "tag": TagResponse,
    "verify_answer": VerifyAnswerResponse,
}


__all__ = [
    "CAPABILITY_INPUTS",
    "CAPABILITY_OUTPUTS",
    "CatalogSnapshot",
    "DescribeImageRequest",
    "ExplainRequest",
    "ImageDescription",
    "MediaAsset",
    "TagRequest",
    "VerifyAnswerRequest",
]
