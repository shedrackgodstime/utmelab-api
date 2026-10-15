"""Response parsing, Pydantic validation, and offset snapping."""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from pipeline.ai.schemas import QuestionAIResponse


def extract_json_block(text: str) -> str:
    """Extracts raw JSON content from LLM response, stripping markdown code fences."""
    text = text.strip()
    # Match ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1].strip()

    return text


def sanitize_ai_prose(text: Optional[str]) -> Optional[str]:
    """Sanitizes generated AI prose by removing em dashes, en dashes, and double hyphens."""
    if not text:
        return text
    # Replace em-dashes and en-dashes with appropriate punctuation
    cleaned = re.sub(r"\s*[—–]\s*", ", ", text)
    cleaned = re.sub(r"\s*--\s*", ", ", cleaned)
    # Clean up any duplicate commas or awkward punctuation combos
    cleaned = re.sub(r",\s*,+", ", ", cleaned)
    cleaned = re.sub(r"\.\s*,+", ". ", cleaned)
    cleaned = re.sub(r",\s*\.", ".", cleaned)
    return cleaned.strip()


def parse_and_snap_response(raw_text: str, stem: str) -> Tuple[QuestionAIResponse, List[Dict[str, Any]]]:
    """Parses LLM JSON response, validates with Pydantic, snaps underline offsets, and sanitizes prose."""
    clean_json = extract_json_block(raw_text)
    data = json.loads(clean_json)
    response = QuestionAIResponse.model_validate(data)

    # Sanitize prose fields against em dashes and formatting slop
    if response.audit_report:
        response.audit_report = sanitize_ai_prose(response.audit_report)
    if response.reasoning:
        response.reasoning = sanitize_ai_prose(response.reasoning)
    if response.explanation:
        if response.explanation.key_point:
            response.explanation.key_point = sanitize_ai_prose(response.explanation.key_point)
        if response.explanation.body:
            response.explanation.body = sanitize_ai_prose(response.explanation.body)
        if response.explanation.trap:
            response.explanation.trap = sanitize_ai_prose(response.explanation.trap)

    detected_marks: List[Dict[str, Any]] = []

    # Snap underline offset if present
    if response.underline and response.underline.target_text:
        target = response.underline.target_text.strip()
        offset = response.underline.offset_in_stem if response.underline.offset_in_stem is not None else 0

        if target:
            target_len = len(target)
            # Check if current offset is already accurate
            if (
                0 <= offset <= len(stem) - target_len
                and stem[offset : offset + target_len].lower() == target.lower()
            ):
                snapped_offset = offset
            else:
                # Find exact or case-insensitive match in stem
                found_idx = stem.find(target)
                if found_idx == -1:
                    found_idx = stem.lower().find(target.lower())
                snapped_offset = found_idx

            if snapped_offset != -1:
                response.underline.offset_in_stem = snapped_offset
                detected_marks.append(
                    {
                        "type": "Underline",
                        "range": [snapped_offset, snapped_offset + target_len],
                    }
                )
            else:
                # Target not found in stem at all; discard hallucinated underline
                response.underline = None

    return response, detected_marks

