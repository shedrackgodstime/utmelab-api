"""Verifications, and the vocabulary that decides what counts as verified.

The API's ``verified_predicate`` in ``src/store/catalog.rs`` is the reader's
half of this: it requires a ``human`` verification whose ``verdict`` is
``pass``, whose ``scope`` names both ``answer`` and ``explanation``, and whose
``content_hash`` equals the question's, with no later such row. This module is
the writer's half, and the constants here exist so we never spell those values
from memory.

The bank is stricter for a row that carries a passage: review also requires the
``passage`` scope, because a comprehension key is not verified without its
stimulus. The API ignores the extra scope.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from utmelab_bank.model.base import BankModel

__all__ = [
    "AI",
    "HUMAN",
    "PASS",
    "SCOPE_ANSWER",
    "SCOPE_EXPLANATION",
    "SCOPE_PASSAGE",
    "Scope",
    "Verdict",
    "Verification",
    "VerifierKind",
]

VerifierKind = Literal["human", "ai_describe", "ai_explain", "ai_tag", "ai_verify", "ai_bulk"]
Verdict = Literal["pass", "fail", "disagree", "ambiguous"]
Scope = Literal["answer", "explanation", "passage", "subtopic", "media", "formatting"]

#: The only kind the API counts. A model verification must never use it.
HUMAN: VerifierKind = "human"
AI: VerifierKind = "ai_verify"
PASS: Verdict = "pass"
SCOPE_ANSWER: Scope = "answer"
SCOPE_EXPLANATION: Scope = "explanation"
SCOPE_PASSAGE: Scope = "passage"


class Verification(BankModel):
    """One verdict on one row, attributable and stamped.

    ``content_hash`` is copied from the row at the moment of judging. If the row
    changes afterwards, this verification no longer joins and the row reads as
    unverified, which is the correct behaviour: a verdict about old content is
    not a verdict about new content.
    """

    id: str = Field(min_length=1, max_length=200)
    question_id: str = Field(min_length=1, max_length=200)
    kind: VerifierKind
    verdict: Verdict
    scope: list[Scope]
    verifier: str = Field(min_length=1, max_length=120)
    detail: str | None = None
    content_hash: str = Field(min_length=1)
    created_at: str

    @model_validator(mode="after")
    def _a_human_pass_covers_both(self) -> Verification:
        """A human pass that omits a scope cannot make a row verified.

        Enforced here rather than trusted, because the API silently treats a
        narrow scope as not verified and there is no error anywhere, only a
        question that never shows up as verified.
        """
        if self.kind == HUMAN and self.verdict == PASS:
            needed = {SCOPE_ANSWER, SCOPE_EXPLANATION}
            if not needed.issubset(set(self.scope)):
                missing = sorted(needed - set(self.scope))
                raise ValueError(f"a human pass must cover {missing}")
        return self

    @property
    def counts_as_verified(self) -> bool:
        """Whether the API would accept this row as verified."""
        return (
            self.kind == HUMAN
            and self.verdict == PASS
            and {SCOPE_ANSWER, SCOPE_EXPLANATION}.issubset(set(self.scope))
        )
