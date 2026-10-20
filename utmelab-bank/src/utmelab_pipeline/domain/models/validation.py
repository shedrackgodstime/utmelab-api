"""Gate decisions and verification records."""

from pydantic import AwareDatetime, Field, model_validator

from ..enums import Severity, VerificationKind, Verdict
from .common import (
    DomainModel,
    Issue,
    NonEmptyStr,
    Producer,
    Sha256,
)


class GateVerdict(DomainModel):
    passed: bool
    issues: tuple[Issue, ...] = ()
    rules_version: NonEmptyStr = "v1"

    @model_validator(mode="after")
    def _check(self) -> "GateVerdict":
        has_error = any(issue.severity is Severity.ERROR for issue in self.issues)
        if self.passed == has_error:
            raise ValueError("passed must be true exactly when no error issues exist")
        return self


class Verification(DomainModel):
    kind: VerificationKind
    verdict: Verdict
    scope: tuple[NonEmptyStr, ...] = Field(min_length=1)
    content_hash: Sha256
    reviewer: NonEmptyStr
    note: NonEmptyStr | None = None
    created_at: AwareDatetime
    producer: Producer | None = None

    @model_validator(mode="after")
    def _check(self) -> "Verification":
        if self.kind is VerificationKind.AI and self.producer is None:
            raise ValueError("AI verification requires a producer")
        if self.kind is VerificationKind.HUMAN and self.producer is not None:
            raise ValueError("human verification cannot carry a model producer")
        return self
