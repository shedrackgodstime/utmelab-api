"""The myschool source's own refusals.

A source refusal is a per-row failure, not a crash. The fetch task reports it
against the row's source id and carries on with the rest of the page, so one
malformed question does not cost the other four.

The type lives here rather than in the domain because it is the source's, not
the bank's. The domain has no opinion about myschool's envelope.
"""

from __future__ import annotations

from typing import Any


class SourceError(RuntimeError):
    """The source refused, or returned something the parser cannot trust."""

    def __init__(self, detail: str, **context: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.context = context

    def __str__(self) -> str:
        if not self.context:
            return self.detail
        pairs = ", ".join(f"{key}={value!r}" for key, value in sorted(self.context.items()))
        return f"{self.detail} ({pairs})"


__all__ = ["SourceError"]
