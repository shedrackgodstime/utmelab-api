"""Prompt construction for the tagging task.

One prompt per question: the passage when the row carries one, the stem, the
options, the provided answer, the explanation (or MISSING), and the full
subtopic + topic menu so the model has something to choose from. The model must
return JSON only, with a subtopic slug, an underline, an answer check and an
explanation-quality rating.

Ported from ``tools/utmetag/prompt.py``, adapted to read from the bank's work
row (a dict) rather than utmetag's ``QuestionInput`` dataclass.
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_tagging_prompt"]


def _txt(part: Any) -> str:
    if not isinstance(part, dict):
        return ""
    return part.get("text", "") or ""


def _objectives_line(objectives: list[str]) -> str:
    """Render a syllabus objectives list as one indented sub-line, or ''."""
    items = [str(o).strip() for o in (objectives or []) if str(o or "").strip()]
    if not items:
        return ""
    return f"\n      objectives: {'; '.join(items)}"


def build_tagging_prompt(
    question: dict[str, Any],
    subtopics: list[dict[str, Any]],
    topics: list[dict[str, Any]],
) -> str:
    """One prompt for one question, in the shape the model answers from."""
    options_text = "\n".join(f"  {opt['id']}) {_txt(opt['text'])}" for opt in question["options"])

    subtopic_list = "\n".join(
        f"  - {st['slug']}: {st['name']} (topic: {st['topic']})"
        f"{_objectives_line(st.get('objectives', []))}"
        for st in subtopics
    )
    topic_list = "\n".join(
        f"  - {t['slug']}: {t['name']}{_objectives_line(t.get('objectives', []))}" for t in topics
    )

    explanation_text = "MISSING"
    explanation = question.get("explanation")
    if isinstance(explanation, dict) and explanation:
        kp = _txt(explanation.get("key_point"))
        body = _txt(explanation.get("body"))
        trap = _txt(explanation.get("trap"))
        if kp or body or trap:
            explanation_text = f"Key point: {kp}\nBody: {body}\nTrap: {trap}"

    stem = _txt(question["text"])
    passage = str(question.get("passage") or "")
    passage_block = f"\nPASSAGE:\n{passage}\n" if passage else ""

    return f"""You are an expert JAMB examiner. Tag this question with the correct subtopic and identify any underlined word.
{passage_block}
QUESTION:
Subject: {question["subject"]} ({question["exam"]} {question["year"]})
Source: {question["source"]}
Question: {stem}

OPTIONS:
{options_text}

CORRECT ANSWER: {question["answer"]}

EXPLANATION:
{explanation_text}

AVAILABLE SUBTOPICS (choose exactly one, or null if none fit):
{subtopic_list}

AVAILABLE TOPICS (for context):
{topic_list}

TASKS:
1. SUBTOPIC: Choose the single most specific subtopic slug from the list above. If the question spans multiple or none fit well, use null.
2. UNDERLINE: If the question stem contains a phrase like "the underlined word", "the underlined phrase", "underlined below", or similar — extract the EXACT word/phrase that is underlined. Return the word, its start offset (Unicode chars from stem start), and length. If no underline reference, use null.
3. ANSWER CHECK: Verify the provided answer is correct. Explain briefly.
4. EXPLANATION QUALITY: Rate the explanation as GOOD, PARTIAL, POOR, or MISSING.

OUTPUT FORMAT (JSON only):
{{
  "subtopic_slug": "surds" or null,
  "underline": {{"word": "cogent", "start": 24, "len": 6}} or null,
  "answer_correct": true/false,
  "explanation_quality": "GOOD|PARTIAL|POOR|MISSING",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of subtopic choice, underline detection, answer verification, and explanation quality assessment"
}}"""
