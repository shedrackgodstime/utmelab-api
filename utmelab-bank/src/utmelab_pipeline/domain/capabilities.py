"""Capability names and their typed request models."""

from .models import (
    CatalogSnapshot,
    MediaAsset,
)
from .models.common import (
    DescribeImageRequest,
    DescribeImageResponse,
    ExplainRequest,
    ExplainResponse,
    TagRequest,
    TagResponse,
    VerifyAnswerRequest,
    VerifyAnswerResponse,
)


CAPABILITY_INPUTS = {
    "describe_image": DescribeImageRequest,
    "explain": ExplainRequest,
    "tag": TagRequest,
    "verify_answer": VerifyAnswerRequest,
}

CAPABILITY_OUTPUTS = {
    "describe_image": DescribeImageResponse,
    "explain": ExplainResponse,
    "tag": TagResponse,
    "verify_answer": VerifyAnswerResponse,
}