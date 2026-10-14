"""Provider registry — the factory that maps an engine name to a Provider.

This is the one place that knows about concrete backends. Adding a backend is:
define a class implementing ``Provider`` and register a builder here.

There are exactly two engines, and only one of them talks to a model:

* ``opencode`` (default) — the OpenCode CLI running free Zen models. This is
  the only model backend; the project does not fall back to a paid API.
* ``mock`` — in-process, no network, deterministic; for tests and offline runs.
"""

from __future__ import annotations

from typing import Optional

from .base import Provider
from .mock import MockProvider
from .opencode import OpenCodeProvider

OPENCODE_DEFAULT_MODEL = "opencode/space-bunny-free"


def build_provider(
    engine: str,
    *,
    model: Optional[str] = None,
    opencode_bin: str = "opencode",
    opencode_timeout: float = 180.0,
) -> Provider:
    """Construct a Provider for the named engine."""
    if engine == "mock":
        return MockProvider()

    if engine == "opencode":
        return OpenCodeProvider(
            model=model or OPENCODE_DEFAULT_MODEL,
            binary=opencode_bin,
            timeout=opencode_timeout,
        )

    raise SystemExit(f"unknown engine: {engine!r} (use 'opencode' or 'mock')")


__all__ = [
    "Provider",
    "MockProvider",
    "OpenCodeProvider",
    "OPENCODE_DEFAULT_MODEL",
    "build_provider",
]
