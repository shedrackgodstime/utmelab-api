"""Provider adapters. Each one declares the capabilities it supports."""

from .mock import MockProvider
from .opencode import OpenCodeProvider
from .tagging import ExplainService, TagService, UnknownSubtopic, UnknownTopic

__all__ = [
    "MockProvider",
    "OpenCodeProvider",
    "TagService",
    "ExplainService",
    "UnknownSubtopic",
    "UnknownTopic",
]