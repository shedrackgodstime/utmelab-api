"""Prompt construction for the tagging task (provider-independent)."""

from __future__ import annotations

from typing import Any

from .schema import QuestionInput, SubtopicInfo, TopicInfo


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
    question: QuestionInput,
    subtopics: list[SubtopicInfo],
    topics: list[TopicInfo],
) -> str:
    options_text = "\n".join(f"  {opt['id']}) {opt['text']['text']}" for opt in question.options)

    subtopic_list = "\n".join(
        f"  - {st.slug}: {st.name} (topic: {st.topic}){_objectives_line(st.objectives)}"
        for st in subtopics
    )
    topic_list = "\n".join(
        f"  - {t.slug}: {t.name}{_objectives_line(t.objectives)}"
        for t in topics
    )

    explanation_text = "MISSING"
    if question.explanation:
        kp = _txt(question.explanation.get("key_point"))
        body = _txt(question.explanation.get("body"))
        trap = _txt(question.explanation.get("trap"))
        if kp or body or trap:
            explanation_text = f"Key point: {kp}\nBody: {body}\nTrap: {trap}"

    stem = question.text.get("text", "")

    return f"""You are an expert JAMB examiner. Tag this question with the correct subtopic and identify any underlined word.

QUESTION:
Subject: {question.subject} ({question.exam} {question.year})
Source: {question.source}
Question: {stem}

OPTIONS:
{options_text}

CORRECT ANSWER: {question.answer}

EXPLANATION:
{explanation_text}

AVAILABLE SUBTOPICS (choose exactly one, or null if none fit):
{subtopic_list}

AVAILABLE TOPICS (for context):
{topic_list}

TASKS:
1. SUBTOPIC: Select the single most specific subtopic slug from the list above. If the question spans multiple or none fit well, use null.
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
