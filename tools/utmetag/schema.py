"""Typed schema for the auto-tagging task.

Two families of models live here:

* ``ModelOutput`` is the *structured output contract* we ask the provider to
  emit. It is a pydantic model so a malformed reply fails loudly and can be
  retried, rather than silently producing a half-populated result.
* ``TagResult`` is the internal, provider-independent record we write out.

Keeping these separate is what makes the model backend swappable: the task
layer only ever sees ``ModelOutput``; which provider produced it is irrelevant.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

QUALITY_LEVELS = {"GOOD", "PARTIAL", "POOR", "MISSING", "UNKNOWN"}


# ── Model output contract ──────────────────────────────────────────────────────

class Underline(BaseModel):
    word: str
    start: int = 0
    len: int = 0


class ModelOutput(BaseModel):
    """The JSON object a provider must return for a tagging request."""

    subtopic_slug: Optional[str] = None
    underline: Optional[Underline] = None
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

def model_output_from_text(text: str, extractor) -> ModelOutput:
    """Parse and validate provider text into ``ModelOutput``."""
    if text is None or not text.strip():
        raise ValueError("empty response content")
    data = extractor(text)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return ModelOutput.model_validate(data)


# ── Request-side input models ──────────────────────────────────────────────────

@dataclass
class QuestionInput:
    id: str
    exam: str
    subject: str
    year: int
    source: str
    text: dict
    options: list[dict]
    answer: str
    subtopic_id: Optional[str] = None
    explanation: Optional[dict] = None
    marks: float = 2.5
    difficulty: int = 3


@dataclass
class TopicInfo:
    slug: str
    name: str
    subject: str
    exam: str
    objectives: list[str]


@dataclass
class SubtopicInfo:
    slug: str
    topic: str
    name: str
    objectives: list[str]


# ── Result-side output model ───────────────────────────────────────────────────

@dataclass
class TagResult:
    question_id: str
    assigned_subtopic: Optional[str] = None
    underline_word: Optional[str] = None
    underline_start: Optional[int] = None
    underline_len: Optional[int] = None
    answer_verified: bool = False
    explanation_quality: str = "unknown"
    confidence: float = 0.0
    reasoning: str = ""
    error: Optional[str] = None

    @classmethod
    def from_model_output(cls, question_id: str, out: ModelOutput) -> "TagResult":
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

    def to_dict(self) -> dict:
        return asdict(self)
