"""The media description contract: one figure, one plain-language account.

A description is what a candidate who cannot see the figure still gets right:
what kind of figure it is (diagram, graph, table, photograph), what it shows,
and the values a question about it would need. It is prose, not a verdict —
``ai-verify`` decides whether the figure supports the key; this decides what
the figure *is*.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel, field_validator

__all__ = ["DescribeOutput", "DescribeResult", "describe_output_from_text"]

FIGURE_KINDS = {"diagram", "graph", "table", "photograph", "map", "other"}


class DescribeOutput(BaseModel):
    """The JSON object a provider must return for a describe request."""

    figure_kind: str = "other"
    description: str = ""
    key_values: list[str] = []
    confidence: float = 0.0

    @field_validator("figure_kind", mode="before")
    @classmethod
    def _normalize_kind(cls, v: Any) -> str:
        if v is None:
            return "other"
        text = str(v).strip().lower()
        return text if text in FIGURE_KINDS else "other"

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))

    @field_validator("description", mode="before")
    @classmethod
    def _strip_description(cls, v: Any) -> str:
        return str(v or "").strip()


def describe_output_from_text(text: str, extractor: Any) -> DescribeOutput:
    """Parse and validate provider text into ``DescribeOutput``."""
    if text is None or not text.strip():
        raise ValueError("empty response content")
    data = extractor(text)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return DescribeOutput.model_validate(data)


@dataclass
class DescribeResult:
    """What we learned about one figure, regardless of who told us."""

    media_id: str
    figure_kind: str = "other"
    description: str = ""
    key_values: list[str] | None = None
    confidence: float = 0.0
    error: str | None = None

    @classmethod
    def from_model_output(cls, media_id: str, out: DescribeOutput) -> DescribeResult:
        return cls(
            media_id=media_id,
            figure_kind=out.figure_kind,
            description=out.description,
            key_values=list(out.key_values),
            confidence=out.confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
