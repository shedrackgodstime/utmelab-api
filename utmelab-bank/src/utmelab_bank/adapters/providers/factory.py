"""Choose the provider that answers the text capabilities.

The routing-driven ``config`` provider is the real one, and ``opencode`` and
``openai`` remain legacy shortcuts. The route's protocol chooses the adapter,
so a new transport does not add a branch here. There is no mock route: a double
that answers without a model must never be reachable from the CLI, because the
tag it writes is indistinguishable from a real one once it reaches the bank.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TypeVar, cast

from utmelab_bank.config import ConfigError, Settings
from utmelab_bank.domain.capabilities import ExplainRequest, TagRequest, VerifyAnswerRequest
from utmelab_bank.domain.models import (
    AnswerVerdict,
    Explanation,
    TagProposal,
)
from utmelab_bank.domain.ports import AnswerVerifier, Explainer, Tagger
from utmelab_bank.routing import (
    DEFAULT_FAILOVER_CATEGORIES,
    DEFAULT_NO_FAILOVER_CATEGORIES,
    ProviderRoute,
    select_routes,
)

from .openai_compatible import OpenAICompatibleProvider
from .opencode import OpenCodeProvider

#: Every text provider the runner knows how to build.
KNOWN_PROVIDERS = ("opencode", "openai", "config")

_R = TypeVar("_R")


class ProviderExhausted(RuntimeError):
    """Every route failed with a retryable error, so the batch must stop.

    Raising this is the limit, not the report: the run stops instead of
    asking three dead providers about every remaining row.
    """

    def __init__(
        self,
        message: str,
        *,
        routes: tuple[str, ...] = (),
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.routes = routes
        if cause is not None:
            self.__cause__ = cause


def _is_retryable(exc: BaseException, route: ProviderRoute | None = None) -> bool:
    """Classify one failure with the route's manifest ``error_policy``.

    ``do_not_failover`` wins over ``failover_to_next_account`` so a declared
    policy is authoritative. A 5xx with no category is still treated as a
    transient provider failure.
    """
    failover = route.failover_categories if route else DEFAULT_FAILOVER_CATEGORIES
    no_failover = route.no_failover_categories if route else DEFAULT_NO_FAILOVER_CATEGORIES
    for e in (exc, getattr(exc, "__cause__", None)):
        if e is None:
            continue
        cat = getattr(e, "category", None)
        if cat is not None:
            if cat in no_failover:
                return False
            if cat in failover:
                return True
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
            timeout=route.timeout_seconds,
        )
    if route.protocol == "opencode-cli":
        raw_args = route.transport.get("args")
        args = (
            tuple(str(item) for item in raw_args) if isinstance(raw_args, (list, tuple)) else None
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
        self._exhausted: ProviderExhausted | None = None
        self._last_success: int | None = None
        self._dead_until: dict[int, float] = {}
        self._failures: dict[int, int] = {}
        self._cooldown = max((route.cooldown_seconds for route in routes), default=300.0)
        self._max_cooldown = max((route.max_cooldown_seconds for route in routes), default=3600.0)
        self.producer = create_from_route(routes[0]).producer
        self._log = logging.getLogger(__name__)

    def _build(self) -> OpenAICompatibleProvider | OpenCodeProvider:
        return create_from_route(self._routes[self._current])

    def _update_current(self) -> None:
        self.producer = self._build().producer

    async def _try_routes(self, method_name: str, request: Any) -> _R:
        if self._exhausted is not None:
            # The previous row used every route and every failure was
            # retryable. Asking the same dead providers again only burns the
            # rest of the batch.
            raise self._exhausted

        last_exc: BaseException | None = None
        tried: list[str] = []
        now = time.monotonic()
        cooling = {i for i, _ in enumerate(self._routes) if self._dead_until.get(i, 0.0) > now}
        if cooling:
            self._log.info(
                "skipping %d cooling route(s) of %d after recent retryable failures",
                len(cooling),
                len(self._routes),
            )
        for i, route in enumerate(self._routes):
            if i in cooling:
                continue
            self._current = i
            self._update_current()
            tried.append(f"{route.provider}/{route.model_key}")
            provider = self._build()
            try:
                method = getattr(provider, method_name)
                result = cast(_R, await method(request))
                self._dead_until.pop(i, None)
                self._failures.pop(i, None)
                if i != self._last_success:
                    self._log.info(
                        "using route %d/%d: provider=%s model=%s account=%s",
                        i + 1,
                        len(self._routes),
                        route.provider,
                        route.model_id,
                        route.account_id,
                    )
                    self._last_success = i
                return result
            except BaseException as exc:
                last_exc = exc
                if not _is_retryable(exc, route):
                    self._log.error(
                        "not failing over for %s: route=%s provider=%s model=%s error=%s",
                        method_name,
                        route.model_key,
                        route.provider,
                        route.model_id,
                        exc,
                    )
                    raise
                failures = self._failures.get(i, 0) + 1
                self._failures[i] = failures
                threshold = max(1, route.max_consecutive_failures)
                if failures < threshold:
                    self._log.warning(
                        "failover %s: route=%s provider=%s model=%s error=%s "
                        "-> trying next (failure %d below cooldown threshold %d)",
                        method_name,
                        route.model_key,
                        route.provider,
                        route.model_id,
                        exc,
                        failures,
                        threshold,
                    )
                    continue
                delay = min(
                    self._cooldown * (2 ** (failures - threshold)),
                    self._max_cooldown,
                )
                self._dead_until[i] = time.monotonic() + delay
                self._log.warning(
                    "failover %s: route=%s provider=%s model=%s error=%s "
                    "-> cooling down %.0fs (failure %d), trying next",
                    method_name,
                    route.model_key,
                    route.provider,
                    route.model_id,
                    exc,
                    delay,
                    failures,
                )
        if cooling and not tried:
            message = (
                f"all {len(self._routes)} provider route(s) are cooling down "
                f"after retryable failures"
            )
        else:
            message = f"all {len(self._routes)} provider route(s) failed: {last_exc}"
        self._exhausted = ProviderExhausted(message, routes=tuple(tried), cause=last_exc)
        self._log.error("provider exhausted: %s", message)
        raise self._exhausted from last_exc

    async def explain(self, request: ExplainRequest) -> Explanation:
        return await self._try_routes("explain", request)

    async def tag(self, request: TagRequest) -> TagProposal:
        return await self._try_routes("tag", request)

    async def verify(self, request: VerifyAnswerRequest) -> AnswerVerdict:
        return await self._try_routes("verify", request)


def create_text_provider(
    name: str, *, settings: Settings, task: str = "question_explanation"
) -> OpenCodeProvider | OpenAICompatibleProvider | FailoverProvider:
    """Build a provider by name.

    The returned object satisfies the tag, explain and verify ports. A name
    the runner does not know is a configuration error.
    """
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


__all__ = [
    "KNOWN_PROVIDERS",
    "FailoverProvider",
    "ProviderExhausted",
    "create_from_route",
    "create_text_provider",
]
