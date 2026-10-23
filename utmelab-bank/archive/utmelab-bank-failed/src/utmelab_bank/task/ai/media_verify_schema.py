"""Typed schema for the media verification task.

A description is usable only when a second check has looked at the same figure
and found every claim supported. The schema is deliberately fail-closed: a
model that says pass while failing fidelity, failing fit, quoting no evidence,
or marking any claim unsupported gets a fail. A generous verifier cannot wave a
bad description through.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, field_validator

__all__ = [
    "Claim",
    "MediaVerifyOutput",
    "MediaVerifyResult",
    "media_verify_output_from_text",
]

CLAIM_STATUSES = {"supported", "unsupported", "contradicted"}

#: Below this the check is not confident enough to call the description usable.
MIN_CONFIDENCE = 0.6


def _pass_fail(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"pass", "fail"} else "fail"


class Claim(BaseModel):
    """One factual statement from the description, and what the figure shows."""

    claim: str = ""
    status: str = "unsupported"
    evidence: str = ""

    @field_validator("claim", "evidence", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in CLAIM_STATUSES else "unsupported"


class MediaVerifyOutput(BaseModel):
    """The JSON object a provider must return for a media check."""

    verdict: str = "fail"
    fidelity: str = "fail"
    fit: str = "fail"
    confidence: float = 0.0
    claims: list[Claim] = []
    reasoning: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _normalize_verdict(cls, value: Any) -> str:
        return _pass_fail(value)

    @field_validator("fidelity", "fit", mode="before")
    @classmethod
    def _normalize_dimension(cls, value: Any) -> str:
        return _pass_fail(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, number))

    @field_validator("claims", mode="before")
    @classmethod
    def _keep_claim_objects(cls, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, (dict, Claim))]

    @field_validator("reasoning", mode="before")
    @classmethod
    def _strip_reasoning(cls, value: Any) -> str:
        return str(value or "").strip()


def media_verify_output_from_text(text: str, extractor: Any) -> MediaVerifyOutput:
    """Parse and validate provider text into ``MediaVerifyOutput``."""
    if text is None or not text.strip():
        raise ValueError("empty response content")
    data = extractor(text)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return MediaVerifyOutput.model_validate(data)


def _enforce(out: MediaVerifyOutput, claims: list[dict[str, Any]]) -> tuple[str, str]:
    """Downgrade a generous pass to a fail, and say why."""
    if out.verdict != "pass":
        return "fail", ""
    if out.fidelity != "pass":
        return "fail", "fidelity failed"
    if out.fit != "pass":
        return "fail", "the figure does not fit the question"
    if not claims:
        return "fail", "no claims were checked"
    if not out.reasoning:
        return "fail", "no evidence was quoted"
    if out.confidence < MIN_CONFIDENCE:
        return "fail", f"confidence {out.confidence:.2f} is below {MIN_CONFIDENCE}"
    unsupported = [claim for claim in claims if claim["status"] != "supported"]
    if unsupported:
        first = unsupported[0]
        return "fail", f"{len(unsupported)} claim(s) not supported: {first['claim'][:80]}"
    return "pass", ""


@dataclass
class MediaVerifyResult:
    """What the second check found about one figure description."""

    media_id: str
    verdict: str = "fail"
    fidelity: str = "fail"
    fit: str = "fail"
    confidence: float = 0.0
    claims: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    error: str | None = None

    @classmethod
    def from_model_output(cls, media_id: str, out: MediaVerifyOutput) -> MediaVerifyResult:
        claims = [claim.model_dump() for claim in out.claims]
        verdict, downgrade = _enforce(out, claims)
        reasoning = out.reasoning
        if downgrade:
            reasoning = f"downgraded from pass: {downgrade}. {reasoning}".strip()
        return cls(
            media_id=media_id,
            verdict=verdict,
            fidelity=out.fidelity,
            fit=out.fit,
            confidence=out.confidence,
            claims=claims,
            reasoning=reasoning,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
