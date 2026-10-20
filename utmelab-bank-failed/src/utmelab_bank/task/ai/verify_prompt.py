"""Prompt construction for the verify task.

The model sees everything the earlier tasks produced — stem, options, answer,
explanation (key_point/body/trap) and subtopic — and returns a pass/fail
verdict with which scopes it checked. The prompt demands the model quote the
evidence: a pass with no quoted evidence is a guess, not a verdict.
"""

from __future__ import annotations

__all__ = ["build_verify_prompt"]


def build_verify_prompt(
    stem: str,
    options: list[str],
    answer: str,
    key_point: str,
    body: str,
    trap: str,
    subtopic: str,
    *,
    passage: str = "",
) -> str:
    """One prompt for one fully-tagged question."""
    options_text = "\n".join(f"  {text}" for text in options) if options else "(no options given)"
    passage_block = f"\nPASSAGE:\n{passage}\n" if passage else ""

    return f"""You are verifying a JAMB exam question before it ships to candidates. Be strict: a wrong key in production cannot be recalled.
{passage_block}
QUESTION:
{stem}

ITS OPTIONS:
{options_text}

CLAIMED ANSWER: {answer}

CLAIMED SUBTOPIC: {subtopic or "(none assigned)"}

CLAIMED EXPLANATION:
Key point: {key_point or "(missing)"}
Body: {body or "(missing)"}
Trap: {trap or "(missing)"}

TASKS:
1. VERDICT: pass only if the claimed answer is actually correct AND the explanation is accurate. Otherwise fail.
2. SCOPE: which of answer | explanation | passage | subtopic | media | formatting you checked. Include passage whenever the question carries one.
3. Quote the evidence for your verdict. A comprehension key that contradicts the passage fails.

OUTPUT FORMAT (JSON only):
{{
  "verdict": "pass" or "fail",
  "scope": ["answer", "explanation"],
  "confidence": 0.0-1.0,
  "reasoning": "The key is correct because ...; the explanation ...; evidence: ..."
}}"""
