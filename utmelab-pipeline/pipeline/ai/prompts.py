"""Prompt generation and syllabus pruning for AI verification."""

import json
from typing import Any, Dict, List, Optional


def build_verification_prompt(
    stem: str,
    options: List[Dict[str, str]],
    recorded_answer: str,
    subject: str,
    syllabus: Dict[str, Any],
    recorded_explanation: Optional[str] = None,
    has_image: bool = False,
    passage_text: Optional[str] = None,
) -> str:
    """Builds the comprehensive verification prompt with syllabus context and passage stimulus."""
    options_text = "\n".join([f"  {opt['id']}) {opt['text']}" for opt in options])

    # Format syllabus subtopics
    subtopics_list = syllabus.get("subtopics", [])
    topics_map = {t["slug"]: t for t in syllabus.get("topics", [])}

    subtopics_formatted = []
    for s in subtopics_list:
        slug = s["slug"]
        name = s["name"]
        topic_slug = s.get("topic_slug", "")
        topic_name = topics_map.get(topic_slug, {}).get("name", topic_slug)
        subtopics_formatted.append(f"- {slug}: {name} (Topic: {topic_name})")

    subtopics_block = "\n".join(subtopics_formatted) if subtopics_formatted else "None provided."

    image_note = (
        "NOTE: A diagram image is attached to this prompt as visual context. "
        "Inspect the diagram carefully to calculate or derive the correct answer."
        if has_image
        else ""
    )

    passage_block = (
        f"\n=== PASSAGE STIMULUS ===\n{passage_text}\n"
        if passage_text
        else ""
    )

    prompt = f"""You are an expert academic examiner and curriculum specialist for Nigerian secondary education ({subject.upper()}).
Your task is to independently verify this examination question, evaluate its answer key, select the exact syllabus subtopic, and review the explanation.

{image_note}
{passage_block}
=== QUESTION STEM ===
{stem}

=== OPTIONS ===
{options_text}

=== RECORDED ANSWER KEY ===
Option: {recorded_answer}

=== RECORDED EXPLANATION ===
{recorded_explanation or "None provided."}

=== AVAILABLE SYLLABUS SUBTOPICS ===
You MUST select the single best subtopic slug from this official list:
{subtopics_block}

=== INSTRUCTIONS & RULES ===
1. Verify the answer independently. Compute or derive the answer from scratch.
   - If the recorded key is correct, set "answer_check": "VERIFIED".
   - If the recorded key is incorrect, set "answer_check": "DISAGREEMENT" and explain why in "reasoning".
   - If the question is ambiguous or impossible to solve, set "answer_check": "AMBIGUOUS".
2. Select the single most accurate "subtopic_slug" from the provided list. Do NOT invent a slug.
3. If the stem contains or requires an underlined word/phrase (e.g. nearest in meaning, antonym, word stress), extract it into "underline" with target_text and character offset.
4. Assess explanation quality: "GOOD", "PARTIAL", "POOR", or "MISSING". If missing or poor, provide an author-grade explanation:
   - key_point: One-sentence core principle or formula.
   - body: Clear step-by-step reasoning or mathematical proof.
   - trap: Explanation of why distractors are tempting.
5. Provide a confidence score between 0.0 and 1.0.
6. Write a crisp 1-2 sentence "audit_report" summarizing: visual evidence inspected from diagram (if any), answer verification outcome, and final conclusion.

Respond with ONLY valid JSON matching this schema:
{{
  "subtopic_slug": "exact-slug-from-list",
  "answer_check": "VERIFIED" | "DISAGREEMENT" | "AMBIGUOUS",
  "explanation_quality": "GOOD" | "PARTIAL" | "POOR" | "MISSING",
  "confidence": 0.95,
  "audit_report": "1-2 sentence executive audit summary for human review",
  "underline": {{
    "target_text": "word",
    "offset_in_stem": 12
  }},
  "explanation": {{
    "key_point": "One-sentence principle",
    "body": "Step-by-step derivation",
    "trap": "Why distractor is tempting"
  }},
  "reasoning": "Concise justification of answer and subtopic choice"
}}
"""
    return prompt.strip()
