"""Provider adapters. Each one declares the capabilities it supports."""

from .factory import KNOWN_PROVIDERS, create_text_provider
from .mock import MockProvider
from .opencode import OpenCodeProvider
from .tagging import ExplainService, TagService, UnknownSubtopic, UnknownTopic

__all__ = [
    "ExplainService",
    "KNOWN_PROVIDERS",
    "MockProvider",
    "OpenCodeProvider",
    "TagService",
    "UnknownSubtopic",
    "UnknownTopic",
    "create_text_provider",
]
