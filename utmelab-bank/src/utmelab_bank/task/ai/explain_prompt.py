"""Prompt construction for the explain task.

The model writes a three-part explanation: the key point, the body, and the
trap. These map onto the answer+explanation scopes the API's ``verified``
predicate joins on, so a human pass on both makes the row verified.
"""

from __future__ import annotations

__all__ = ["build_explain_prompt"]


def build_explain_prompt(stem: str, options: list[str], answer: str) -> str:
    """One prompt for one question, asking for key_point / body / trap."""
    options_text = "\n".join(f"  {text}" for text in options) if options else "(no options given)"

    return f"""You are writing an explanation for a JAMB exam question bank. The explanation must teach a candidate how to answer, not just state the key.

QUESTION:
{stem}

ITS OPTIONS:
{options_text}

CORRECT ANSWER: {answer}

TASKS:
1. KEY POINT: one sentence stating the deciding fact or rule.
2. BODY: a short worked explanation a candidate can follow step by step.
3. TRAP: the wrong option candidates most often pick, and why it is wrong.

OUTPUT FORMAT (JSON only):
{{
  "key_point": "...",
  "body": "...",
  "trap": "...",
  "confidence": 0.0-1.0
}}"""
