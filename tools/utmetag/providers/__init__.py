"""Provider registry — the factory that maps an engine name to a Provider.

This is the one place that knows about concrete backends. Adding a backend is:
define a class implementing ``Provider`` and register a builder here.
"""

from __future__ import annotations

import os
from typing import Optional

from .base import Provider
from .http import HTTPProvider
from .mock import MockProvider
from .opencode import OpenCodeProvider

#: Free, no-key HTTP endpoints, keyed by provider name.
HTTP_PRESETS = {
    "pollinations": {
        "base_url": "https://text.pollinations.ai/openai",
        "model": "openai",
        "key_env": None,
        "min_interval": 30.0,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "min_interval": 0.0,
    },
}

OPCODE_DEFAULT_MODEL = "opencode/space-bunny-free"


def resolve_http_provider(
    requested: str,
    no_api_key: bool,
    env: Optional[dict] = None,
) -> str:
    """Resolve ``auto`` to a concrete HTTP preset name."""
    env = env if env is not None else os.environ
    if requested != "auto":
        return requested
    if no_api_key:
        return "pollinations"
    return "openai" if env.get("OPENAI_API_KEY") else "pollinations"


def build_provider_with_cap(
    engine: str,
    *,
    model: Optional[str] = None,
    opencode_bin: str = "opencode",
    opencode_timeout: float = 180.0,
    http_provider: str = "auto",
    base_url: Optional[str] = None,
    no_api_key: bool = False,
    rate_limit_sec: Optional[float] = None,
) -> tuple[Provider, Optional[int]]:
    """Build a provider and report any concurrency cap it imposes.

    ``concurrency_cap`` is ``1`` for rate-limited HTTP providers, else ``None``.
    """
    if engine == "mock":
        return MockProvider(), None

    if engine == "opencode":
        return OpenCodeProvider(
            model=model or OPCODE_DEFAULT_MODEL,
            binary=opencode_bin,
            timeout=opencode_timeout,
        ), None

    if engine == "http":
        name = resolve_http_provider(http_provider, no_api_key)
        preset = HTTP_PRESETS[name]
        api_key = None
        if preset["key_env"]:
            api_key = os.environ.get(preset["key_env"]) or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise SystemExit(f"provider '{name}' requires env {preset['key_env']}")
        min_interval = rate_limit_sec if rate_limit_sec is not None else preset["min_interval"]
        cap = 1 if min_interval > 0 else None
        return HTTPProvider(
            api_key=api_key,
            base_url=base_url or preset["base_url"],
            model=model or preset["model"],
            min_interval=min_interval,
        ), cap

    raise SystemExit(f"unknown engine: {engine!r}")


__all__ = [
    "Provider",
    "MockProvider",
    "OpenCodeProvider",
    "HTTPProvider",
    "HTTP_PRESETS",
    "OPCODE_DEFAULT_MODEL",
    "build_provider_with_cap",
    "resolve_http_provider",
]
