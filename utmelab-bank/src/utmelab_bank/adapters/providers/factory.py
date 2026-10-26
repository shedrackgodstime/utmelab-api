"""Choose the provider that answers the text capabilities.

The mock provider proves the wiring without a model. The routing-driven
``config`` provider is the real one, and ``opencode`` and ``openai`` remain
legacy shortcuts. The route's protocol chooses the adapter, so a new transport
does not add a branch here.
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine, TypeVar, cast
import logging

from utmelab_bank.config import ConfigError, Settings
from utmelab_bank.routing import ProviderRoute, select_routes
from utmelab_bank.domain.capabilities import ExplainRequest, TagRequest, VerifyAnswerRequest
from utmelab_bank.domain.models import (
    AnswerVerdict,
    Explanation,
    Producer,
    TagProposal,
)
from utmelab_bank.domain.ports import AnswerVerifier, Explainer, Tagger

from .mock import MockProvider
from .openai_compatible import OpenAICompatibleProvider, OpenAICompatibleError
from .opencode import OpenCodeProvider, OpenCodeError

#: Every text provider the runner knows how to build.
KNOWN_PROVIDERS = ("mock", "opencode", "openai", "config")

#: Error categories that trigger failover to the next route.
RETRYABLE_CATEGORIES = frozenset(
    {
        "rate_limit",
        "quota",
        "timeout",
        "provider_unavailable",
        "upstream",
        "transport",
    }
)

_R = TypeVar("_R")


def _is_retryable(exc: BaseException) -> bool:
    for e in (exc, getattr(exc, "__cause__", None)):
        if e is None:
            continue
        cat = getattr(e, "category", None)
        if cat in RETRYABLE_CATEGORIES:
            return True
        # OpenAI status 5xx without category -> provider_unavailable
        status = getattr(e, "status", None)
        if isinstance(status, int) and 500 <= status < 600:
            return True
    return False


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


class FailoverProvider(Tagger, Explainer, AnswerVerifier):
    """Try each route in order, failing over on retryable errors."""

    def __init__(self, routes: tuple[ProviderRoute, ...]) -> None:
        if not routes:
            raise ConfigError("provider routing has no usable text route")
        self._routes = routes
        self._current = 0
        self.producer = create_from_route(routes[0]).producer
        self._log = logging.getLogger(__name__)

    def _build(self) -> OpenAICompatibleProvider | OpenCodeProvider:
        return create_from_route(self._routes[self._current])

    def _update_current(self) -> None:
        self.producer = self._build().producer

    async def _try_routes(self, method_name: str, request: Any) -> _R:
        last_exc: BaseException | None = None
        for i in range(len(self._routes)):
            self._current = i
            self._update_current()
            route = self._routes[i]
            provider = self._build()
            try:
                method = getattr(provider, method_name)
                return cast(_R, await method(request))
            except BaseException as exc:
                last_exc = exc
                if not _is_retryable(exc) or i == len(self._routes) - 1:
                    self._log.error(
                        "failover exhausted for %s: route=%s provider=%s model=%s error=%s",
                        method_name,
                        route.model_key,
                        route.provider,
                        route.model_id,
                        exc,
                    )
                    raise
                self._log.warning(
                    "failover %s: route=%s provider=%s model=%s error=%s -> trying next",
                    method_name,
                    route.model_key,
                    route.provider,
                    route.model_id,
                    exc,
                )
        raise last_exc or ConfigError("all routes exhausted")

    async def explain(self, request: ExplainRequest) -> Explanation:
        return await self._try_routes("explain", request)

    async def tag(self, request: TagRequest) -> TagProposal:
        return await self._try_routes("tag", request)

    async def verify(self, request: VerifyAnswerRequest) -> AnswerVerdict:
        return await self._try_routes("verify", request)


def create_text_provider(
    name: str, *, settings: Settings, task: str = "question_explanation"
) -> MockProvider | OpenCodeProvider | OpenAICompatibleProvider | FailoverProvider:
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
        if len(routes) == 1:
            return create_from_route(routes[0])
        return FailoverProvider(routes)
    known = ", ".join(KNOWN_PROVIDERS)
    raise ConfigError(f"unknown provider {name!r}; known providers: {known}")


__all__ = ["KNOWN_PROVIDERS", "create_from_route", "create_text_provider", "FailoverProvider"]
