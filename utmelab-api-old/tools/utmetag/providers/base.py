"""Provider seam: the one interface a model backend must satisfy.

One method, ``async complete(prompt) -> str``. The task and runner layers never
import a concrete backend, so the model backend is swappable by adding a module
and a registry entry in ``providers/__init__.py``. Only the OpenCode CLI backend
talks to a real model today (free); the mock is for tests.
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
        """Release any resources (e.g. subprocesses, clients)."""
        ...
