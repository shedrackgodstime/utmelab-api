"""Provider protocol: the single swap point of the SDK.

Every backend implements ``complete(prompt) -> str``. The task layer never
imports a concrete provider, so dropping in a new backend (a CLI harness, an
HTTP endpoint, a mock) means adding one module and one registry entry.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Provider(Protocol):
    #: Human-readable identifier, e.g. "opencode/space-bunny-free".
    name: str

    async def complete(self, prompt: str) -> str:
        """Return the model's raw text reply for a single prompt."""
        ...

    async def aclose(self) -> None:
        """Release any resources (subprocesses, HTTP clients)."""
        ...
