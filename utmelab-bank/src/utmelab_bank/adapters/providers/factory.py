"""Choose the provider that answers the text capabilities.

The mock provider proves the wiring without a model. The routing-driven
``config`` provider is the real one, and ``opencode`` and ``openai`` remain
legacy shortcuts. The route's protocol chooses the adapter, so a new transport
does not add a branch here.
"""

from __future__ import annotations

from utmelab_bank.config import ConfigError, Settings
from utmelab_bank.routing import ProviderRoute, select_routes

from .mock import MockProvider
from .openai_compatible import OpenAICompatibleProvider
from .opencode import OpenCodeProvider

#: Every text provider the runner knows how to build.
KNOWN_PROVIDERS = ("mock", "opencode", "openai", "config")


def create_from_route(route: ProviderRoute) -> OpenAICompatibleProvider | OpenCodeProvider:
    """Build the adapter named by one resolved route."""
    if route.protocol == "openai-compatible":
        return OpenAICompatibleProvider(
            api_key=route.api_key,
            base_url=route.base_url,
            model=route.model_id,
            provider_name=route.provider,
            account_id=route.account_id,
        )
    if route.protocol == "opencode-cli":
        raw_args = route.transport.get("args")
        args = (
            tuple(str(item) for item in raw_args)
            if isinstance(raw_args, (list, tuple))
            else None
        )
        return OpenCodeProvider(
            model=route.model_id,
            provider=route.provider,
            command=str(route.transport.get("command", "opencode")),
            args=args,
        )
    raise ConfigError(f"unknown provider protocol {route.protocol!r}")


def create_text_provider(
    name: str, *, settings: Settings, task: str = "question_explanation"
) -> MockProvider | OpenCodeProvider | OpenAICompatibleProvider:
    """Build a provider by name.

    The returned object satisfies the tag, explain and verify ports. A name
    the runner does not know is a configuration error.
    """
    if name == "mock":
        return MockProvider()
    if name == "opencode":
        return OpenCodeProvider(model=settings.ai_model)
    if name == "openai":
        if not settings.nvidia_api_key:
            raise ConfigError("the openai-compatible provider needs NVIDIA_API_KEY")
        if not settings.openai_model:
            raise ConfigError("the openai-compatible provider needs OPENAI_MODEL")
        return OpenAICompatibleProvider(
            api_key=settings.nvidia_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
        )
    if name == "config":
        routes = select_routes(task)
        if not routes:
            raise ConfigError("provider routing has no usable text route")
        return create_from_route(routes[0])
    known = ", ".join(KNOWN_PROVIDERS)
    raise ConfigError(f"unknown provider {name!r}; known providers: {known}")


__all__ = ["KNOWN_PROVIDERS", "create_from_route", "create_text_provider"]
