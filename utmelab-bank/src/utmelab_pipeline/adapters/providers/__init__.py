"""Provider adapters. Each one declares the capabilities it supports."""

from .mock import MockProvider
from .opencode import OpenCodeProvider

__all__ = ["MockProvider", "OpenCodeProvider"]