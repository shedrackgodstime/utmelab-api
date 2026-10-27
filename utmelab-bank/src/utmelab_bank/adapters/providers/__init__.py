"""Provider adapters. Each one declares the capabilities it supports."""

from .factory import KNOWN_PROVIDERS, ProviderExhausted, create_text_provider
from .openai_compatible import OpenAICompatibleError, OpenAICompatibleProvider
from .opencode import OpenCodeProvider
from .tagging import ExplainService, LowConfidenceTag, TagService, UnknownSubtopic, UnknownTopic

__all__ = [
    "ExplainService",
    "LowConfidenceTag",
    "KNOWN_PROVIDERS",
    "OpenAICompatibleError",
    "OpenAICompatibleProvider",
    "OpenCodeProvider",
    "ProviderExhausted",
    "TagService",
    "UnknownSubtopic",
    "UnknownTopic",
    "create_text_provider",
]
