"""The model a live test uses, read from the global task routing.

A live test needs a model id, and the routing file is where that id belongs.
The environment variable stays as an escape hatch for a one-off run.
"""

from __future__ import annotations

import os

from utmelab_bank.routing import select_routes


def opencode_model(task: str = "question_explanation") -> str:
    """The OpenCode model the routing file selects for one task."""
    override = os.environ.get("UTMELAB_OPENCODE_MODEL")
    if override:
        return override
    for route in select_routes(task, environment={}):
        if route.family == "opencode":
            return route.model_id
    raise RuntimeError(f"provider routing has no opencode route for {task!r}")
