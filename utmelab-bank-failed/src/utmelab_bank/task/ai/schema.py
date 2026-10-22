"""Typed schema for the auto-tagging task.

Two families of models live here:

- ``ModelOutput`` is the *structured output contract* we ask the provider to
  emit. It is a pydantic model so a malformed reply fails loudly and can be
  retried, rather than silently producing a half-populated result.
- ``TagResult`` is the internal, provider-independent record we write out.

Keeping these separate is what makes the model backend swappable: the task
layer only ever sees ``ModelOutput``; which provider produced it is irrelevant.

Ported from ``tools/utmetag/schema.py`` with the same validators.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel, field_validator

__all__ = [
    "QUALITY_LEVELS",
    "ModelOutput",
    "TagResult",
    "Underline",
    "model_output_from_text",
]

QUALITY_LEVELS = {"GOOD", "PARTIAL", "POOR", "MISSING", "UNKNOWN"}


class Underline(BaseModel):
    """The word the stem points at, with its offsets into the stem text."""

    word: str
    start: int = 0
    len: int = 0


class ModelOutput(BaseModel):
    """The JSON object a provider must return for a tagging request."""

    subtopic_slug: str | None = None
    underline: Underline | None = None
    answer_correct: bool = False
    explanation_quality: str = "UNKNOWN"
    confidence: float = 0.0
    reasoning: str = ""

    @field_validator("explanation_quality", mode="before")
    @classmethod
    def _normalize_quality(cls, v: Any) -> str:
        if v is None:
            return "UNKNOWN"
        text = str(v).strip().upper()
        return text if text in QUALITY_LEVELS else "UNKNOWN"

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))

    @field_validator("underline", mode="before")
    @classmethod
    def _drop_empty_underline(cls, v: Any) -> Any:
        # Models sometimes emit {"word": "", ...} or a non-dict placeholder.
        if isinstance(v, dict) and not str(v.get("word", "") or "").strip():
            return None
        return v


def model_output_from_text(text: str, extractor: Any) -> ModelOutput:
    """Parse and validate provider text into ``ModelOutput``."""
    if text is None or not text.strip():
        raise ValueError("empty response content")
    data = extractor(text)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return ModelOutput.model_validate(data)


# ---------------------------------------------------------------------------
# The internal, provider-independent record
# ---------------------------------------------------------------------------


@dataclass
class TagResult:
    """What we learned about one question, regardless of who told us."""

    question_id: str
    assigned_subtopic: str | None = None
    underline_word: str | None = None
    underline_start: int | None = None
    underline_len: int | None = None
    answer_verified: bool = False
    explanation_quality: str = "unknown"
    confidence: float = 0.0
    reasoning: str = ""
    error: str | None = None

    @classmethod
    def from_model_output(cls, question_id: str, out: ModelOutput) -> TagResult:
        u = out.underline
        return cls(
            question_id=question_id,
            assigned_subtopic=out.subtopic_slug,
            underline_word=u.word if u else None,
            underline_start=u.start if u else None,
            underline_len=u.len if u else None,
            answer_verified=out.answer_correct,
            explanation_quality=out.explanation_quality,
            confidence=out.confidence,
            reasoning=out.reasoning,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
