"""Provider adapters. Each one declares the capabilities it supports."""

from .factory import KNOWN_PROVIDERS, create_text_provider
from .mock import MockProvider
from .openai_compatible import OpenAICompatibleError, OpenAICompatibleProvider
from .opencode import OpenCodeProvider
from .tagging import ExplainService, LowConfidenceTag, TagService, UnknownSubtopic, UnknownTopic

__all__ = [
    "ExplainService",
    "LowConfidenceTag",
    "KNOWN_PROVIDERS",
    "MockProvider",
    "OpenAICompatibleError",
    "OpenAICompatibleProvider",
    "OpenCodeProvider",
    "TagService",
    "UnknownSubtopic",
    "UnknownTopic",
    "create_text_provider",
]
