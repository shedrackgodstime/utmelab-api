"""The review. What is checked, and by whom.

Two halves, and the split matters.

The **gate** checks what a machine can check exactly: bounds, overlaps, the
option count, the url scheme, the catalog links. It is mechanical and it is
total.

The **review** checks what only judgement can: the answer is right, the
explanation teaches, the question is answerable as written, the topic
placement is right. That needs a model or a person.

The scope names what was checked, and the values are production's
``VerifyCheck``. A review that covers the answer and the explanation is the
one the serving predicate understands, so those two are the ones the bank
records.
"""

from __future__ import annotations

from .enums import VerificationKind

#: The checks a review can cover. The values are production's ``VerifyCheck``.
ANSWER = "answer"
EXPLANATION = "explanation"
TOPIC_LINK = "topic_link"
MARKS = "marks"
BOUNDS = "bounds"
DUPE = "dupe"

#: The scope a semantic review records.
#:
#: The answer and the explanation are the two the serving predicate reads. A
#: review that does not cover both cannot serve the row, whatever it says
#: about the others.
REVIEW_SCOPE: tuple[str, ...] = (ANSWER, EXPLANATION, TOPIC_LINK)

#: The scope a mechanical check records. The gate covers these already.
RULE_SCOPE: tuple[str, ...] = (ANSWER, MARKS, BOUNDS, DUPE)


def review_kind(bulk: bool) -> VerificationKind:
    """The kind for a review.

    A bulk run and a single careful check are different evidence, so they
    stay different kinds.
    """
    return VerificationKind.AI_BULK if bulk else VerificationKind.AI_SINGLE


__all__ = [
    "ANSWER",
    "BOUNDS",
    "DUPE",
    "EXPLANATION",
    "MARKS",
    "REVIEW_SCOPE",
    "RULE_SCOPE",
    "TOPIC_LINK",
    "review_kind",
]
