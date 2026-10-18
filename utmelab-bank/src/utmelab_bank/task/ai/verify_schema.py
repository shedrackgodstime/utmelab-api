"""Typed schema for the verify task.

``VerifyOutput`` is the structured output contract we ask the provider to
emit for a verification: a verdict plus which scopes it checked.
``VerifyResult`` is the internal record we write to the work lane.

An AI verdict never makes a row verified — only ``kind='human'`` with
``verdict='pass'`` over answer+explanation does that (see
``model/verification.py``). These rows are the signal reviewers read.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel, field_validator

__all__ = ["VERIFY_SCOPES", "VerifyOutput", "VerifyResult", "verify_output_from_text"]

VERIFY_SCOPES = {"answer", "explanation", "subtopic", "media", "formatting"}


class VerifyOutput(BaseModel):
    """The JSON object a provider must return for a verify request."""

    verdict: str = "fail"
    scope: list[str] = ["answer", "explanation"]
    confidence: float = 0.0
    reasoning: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _normalize_verdict(cls, v: Any) -> str:
        if v is None:
            raise ValueError("the model returned no verdict")
        text = str(v).strip().lower()
        if text in {"pass", "fail"}:
            return text
        raise ValueError(f"verdict must be pass or fail, got {v!r}")

    @field_validator("scope", mode="before")
    @classmethod
    def _whitelist_scope(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            return ["answer", "explanation"]
        kept = [str(s).strip().lower() for s in v if str(s).strip().lower() in VERIFY_SCOPES]
        return kept or ["answer", "explanation"]

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))


def verify_output_from_text(text: str, extractor: Any) -> VerifyOutput:
    """Parse and validate provider text into ``VerifyOutput``."""
    if text is None or not text.strip():
        raise ValueError("empty response content")
    data = extractor(text)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return VerifyOutput.model_validate(data)


@dataclass
class VerifyResult:
    """What the model judged about one question."""

    question_id: str
    verdict: str = "fail"
    scope: list[str] | None = None
    confidence: float = 0.0
    reasoning: str = ""
    error: str | None = None

    @classmethod
    def from_model_output(cls, question_id: str, out: VerifyOutput) -> VerifyResult:
        return cls(
            question_id=question_id,
            verdict=out.verdict,
            scope=list(out.scope),
            confidence=out.confidence,
            reasoning=str(out.reasoning or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
