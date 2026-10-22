"""Typed schema for the explain task.

``ExplainOutput`` is the structured output contract we ask the provider to
emit for an explanation: a key point, a worked body, and the trap distractor.
``ExplainResult`` is the internal record we write to the database.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel, field_validator

__all__ = ["ExplainOutput", "ExplainResult", "explain_output_from_text"]


class ExplainOutput(BaseModel):
    """The JSON object a provider must return for an explain request."""

    key_point: str = ""
    body: str = ""
    trap: str = ""
    confidence: float = 0.0

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))

    @field_validator("key_point", "body", "trap", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> str:
        return str(v or "").strip()


def explain_output_from_text(text: str, extractor: Any) -> ExplainOutput:
    """Parse and validate provider text into ``ExplainOutput``."""
    if text is None or not text.strip():
        raise ValueError("empty response content")
    data = extractor(text)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return ExplainOutput.model_validate(data)


@dataclass
class ExplainResult:
    """What we learned about one question's explanation."""

    question_id: str
    key_point: str = ""
    body: str = ""
    trap: str = ""
    confidence: float = 0.0
    error: str | None = None

    @classmethod
    def from_model_output(cls, question_id: str, out: ExplainOutput) -> ExplainResult:
        return cls(
            question_id=question_id,
            key_point=out.key_point,
            body=out.body,
            trap=out.trap,
            confidence=out.confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
