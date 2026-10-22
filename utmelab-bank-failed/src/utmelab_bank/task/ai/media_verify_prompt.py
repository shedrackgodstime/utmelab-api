"""Prompt construction for checking a figure description against the figure.

The model gets the attached figure, the question it belongs to, and the
description another call produced. It is asked for claims, not a vibe: every
number, unit and label in the description must be traced to something visible
on the figure or given in the stem. A pass with no quoted evidence is worthless,
so the schema rejects one.
"""

from __future__ import annotations

__all__ = ["build_media_verify_prompt"]


def build_media_verify_prompt(stem: str, options: list[str], description: str) -> str:
    """One prompt for one figure and the description claiming what it shows."""
    options_text = "\n".join(f"  {text}" for text in options) if options else "(no options given)"

    return f"""You are checking a machine-written description of a figure in a JAMB question bank. The figure is attached. Be strict: a description that invents a value is worse than no description.

THE QUESTION THE FIGURE BELONGS TO:
{stem}

ITS OPTIONS:
{options_text}

THE DESCRIPTION TO CHECK:
{description}

TASKS:
1. FIDELITY: does the description match the attached figure? Check every number, unit, label, axis and component.
2. FIT: does the figure belong to this question? A correct description of the wrong figure fails.
3. CLAIMS: split the description into its factual claims. For each claim, mark supported | unsupported | contradicted and quote what you actually see, for example "label 0.5H beside the coil".
4. VERDICT: pass only if every number and label is supported by the figure or by the question stem, no claim is contradicted, and the figure fits the question. If you cannot read the figure, fail and say so.

OUTPUT FORMAT (JSON only):
{{
  "verdict": "pass" or "fail",
  "fidelity": "pass" or "fail",
  "fit": "pass" or "fail",
  "confidence": 0.0-1.0,
  "claims": [
    {{"claim": "the inductor is 0.5H", "status": "supported", "evidence": "label 0.5H beside the coil"}}
  ],
  "reasoning": "one sentence naming the strongest evidence or the first contradiction"
}}"""
