"""Media failures, shaped for a retry policy.

The distinction that matters is the only one worth making here: a refused
credential reads the same on the next attempt, so it must not be retried; a
declined hook, a dropped connection, or somebody else's lease clears on its
own. Everything carries its context, so a run summary can say what happened
without anyone re-reading git's output.
"""

from __future__ import annotations

from typing import Any


class MediaError(RuntimeError):
    """A media failure that says whether trying again could help."""

    #: Retry by default. The subclasses that must not are the exception.
    retryable = True

    def __init__(self, message: str, *, hint: str | None = None, **context: Any) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context)
        if hint is not None:
            self.context["hint"] = hint

    @property
    def is_retryable(self) -> bool:
        return self.retryable


class MediaAuthError(MediaError):
    """The remote refused the credential. Retrying changes nothing."""

    retryable = False


class MediaPublishError(MediaError):
    """A publish that could not be proven. Retrying the same bytes is pointless."""

    retryable = False


class InsufficientWitnesses(MediaError):
    """The routing cannot name enough different models to check a figure.

    This is the named failure the routing policy asks for when it says
    ``on_insufficient_witnesses: block``. One model, however many accounts it
    has, is not a second opinion; a configuration that can only produce one is
    refused before any figure is described.
    """

    retryable = False


__all__ = ["InsufficientWitnesses", "MediaAuthError", "MediaError", "MediaPublishError"]
