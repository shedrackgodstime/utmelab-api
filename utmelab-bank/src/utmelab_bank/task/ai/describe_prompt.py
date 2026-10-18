"""Prompt construction for the describe task.

The model sees the figure plus the question that references it: a circuit
diagram means one thing under "calculate the current" and another under
"which component is faulty". Without the stem the description drifts to
generic ("a diagram with labels") and misses the values the question needs.
"""

from __future__ import annotations

__all__ = ["build_describe_prompt"]


def build_describe_prompt(stem: str, options: list[str]) -> str:
    """One prompt for one figure, with the referencing question as context."""
    options_text = "\n".join(f"  {text}" for text in options) if options else "(no options given)"

    return f"""You are describing a figure for a JAMB exam question bank. A candidate who cannot see the figure must still be able to answer from your description.

THE QUESTION THAT REFERENCES THIS FIGURE:
{stem}

ITS OPTIONS:
{options_text}

TASKS:
1. FIGURE KIND: one of diagram | graph | table | photograph | map | other.
2. DESCRIPTION: 2-4 sentences saying what the figure shows — the components, labels, axes, or rows a candidate would need. Name every value printed on the figure.
3. KEY VALUES: the list of numbers/labels on the figure that answering needs (e.g. ["12V", "R1 = 4 ohms"]). Empty list when the figure carries no values.

OUTPUT FORMAT (JSON only):
{{
  "figure_kind": "diagram",
  "description": "A series circuit with a 12V battery, a 4 ohm resistor R1 and a 2 ohm resistor R2.",
  "key_values": ["12V", "R1 = 4 ohms", "R2 = 2 ohms"],
  "confidence": 0.0-1.0
}}"""
