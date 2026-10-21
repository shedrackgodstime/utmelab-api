"""Choose the provider that answers the text capabilities.

The mock provider proves the wiring without a model. The OpenCode provider is
the real one. The choice is a name on the command line, so a run can be
rehearsed offline and then repeated with the model without changing code.
"""

from __future__ import annotations

from utmelab_bank.config import ConfigError, Settings

from .mock import MockProvider
from .opencode import OpenCodeProvider

#: Every text provider the runner knows how to build.
KNOWN_PROVIDERS = ("mock", "opencode")


def create_text_provider(name: str, *, settings: Settings) -> MockProvider | OpenCodeProvider:
    """Build a provider by name.

    The returned object satisfies the tag, explain and verify ports. A name
    the runner does not know is a configuration error.
    """
    if name == "mock":
        return MockProvider()
    if name == "opencode":
        return OpenCodeProvider(model=settings.ai_model)
    known = ", ".join(KNOWN_PROVIDERS)
    raise ConfigError(f"unknown provider {name!r}; known providers: {known}")


__all__ = ["KNOWN_PROVIDERS", "create_text_provider"]
