"""Prompt construction for the explain task.

The model writes a three-part explanation: the key point, the body, and the
trap. These map onto the answer+explanation scopes the API's ``verified``
predicate joins on, so a human pass on both makes the row verified.
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_explain_prompt"]


def _objectives(items: Any) -> str:
    values = [str(item).strip() for item in (items or []) if str(item or "").strip()]
    return "; ".join(values)


def _syllabus(topic: dict[str, Any] | None, subtopic: dict[str, Any] | None) -> str:
    lines: list[str] = []
    if topic:
        lines.append(f"Topic: {topic.get('name', '')}")
        objectives = _objectives(topic.get("objectives"))
        if objectives:
            lines.append(f"Topic objectives: {objectives}")
    if subtopic:
        lines.append(f"Subtopic: {subtopic.get('name', '')}")
        objectives = _objectives(subtopic.get("objectives"))
        if objectives:
            lines.append(f"Subtopic objectives: {objectives}")
    return "\n".join(lines)


def build_explain_prompt(
    stem: str,
    options: list[str],
    answer: str,
    *,
    passage: str = "",
    topic: dict[str, Any] | None = None,
    subtopic: dict[str, Any] | None = None,
) -> str:
    """One prompt for one question, asking for key_point / body / trap."""
    options_text = "\n".join(f"  {text}" for text in options) if options else "(no options given)"
    syllabus = _syllabus(topic, subtopic)
    context = f"\nSYLLABUS CONTEXT:\n{syllabus}\n" if syllabus else ""
    passage_block = f"\nPASSAGE:\n{passage}\n" if passage else ""

    return f"""You are writing an explanation for a JAMB exam question bank. The explanation must teach a candidate how to answer, not just state the key.
{passage_block}
QUESTION:
{stem}

ITS OPTIONS:
{options_text}

CORRECT ANSWER: {answer}
{context}
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
