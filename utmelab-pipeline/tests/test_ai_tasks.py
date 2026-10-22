"""Tests for AI response parsing, validation, and offset snapping."""

from pipeline.ai.tasks import extract_json_block, parse_and_snap_response


def test_extract_json_block_strips_fences():
    raw_markdown = """Here is the result:
```json
{
  "subtopic_slug": "projectile-motion",
  "answer_check": "VERIFIED",
  "explanation_quality": "GOOD",
  "confidence": 0.95,
  "reasoning": "Derivation is correct"
}
```
Hope this helps!"""
    extracted = extract_json_block(raw_markdown)
    assert extracted.startswith("{")
    assert extracted.endswith("}")
    assert '"subtopic_slug": "projectile-motion"' in extracted


def test_parse_and_snap_correct_offset():
    stem = "Choose the word opposite in meaning to the underlined word: The general was notorious for his cruelty."
    raw_ai = """{
  "subtopic_slug": "antonyms",
  "answer_check": "VERIFIED",
  "explanation_quality": "GOOD",
  "confidence": 0.95,
  "underline": {
    "target_text": "notorious",
    "offset_in_stem": 999
  },
  "reasoning": "Opposite of notorious is reputable"
}"""
    response, marks = parse_and_snap_response(raw_ai, stem)
    assert response.subtopic_slug == "antonyms"
    assert response.underline is not None
    # Snapped to real index of "notorious" in stem
    expected_idx = stem.find("notorious")
    assert response.underline.offset_in_stem == expected_idx
    assert len(marks) == 1
    assert marks[0]["type"] == "Underline"
    assert marks[0]["range"] == [expected_idx, expected_idx + len("notorious")]


def test_parse_discards_hallucinated_underline_target():
    stem = "What is the boiling point of pure water at standard atmospheric pressure?"
    raw_ai = """{
  "subtopic_slug": "thermal-properties",
  "answer_check": "VERIFIED",
  "explanation_quality": "GOOD",
  "confidence": 0.9,
  "underline": {
    "target_text": "nonexistent_word",
    "offset_in_stem": 10
  },
  "reasoning": "Standard question"
}"""
    response, marks = parse_and_snap_response(raw_ai, stem)
    assert response.underline is None
    assert len(marks) == 0


def test_parse_includes_audit_report():
    stem = "Study the circuit diagram below and calculate the current flowing through R1."
    raw_ai = """{
  "subtopic_slug": "electric-circuits",
  "answer_check": "VERIFIED",
  "explanation_quality": "GOOD",
  "confidence": 0.98,
  "audit_report": "Diagram shows series-parallel network with 12V supply; verified current is 2.0A using Ohm's law.",
  "reasoning": "Standard circuit analysis matching answer key B"
}"""
    response, marks = parse_and_snap_response(raw_ai, stem)
    assert response.subtopic_slug == "electric-circuits"
    assert response.confidence == 0.98
    assert "series-parallel" in response.audit_report


def test_sanitize_ai_prose_strips_em_dashes():
    stem = "Calculate the momentum of a 2kg mass moving at 5m/s."
    raw_ai = """{
  "subtopic_slug": "linear-momentum",
  "answer_check": "VERIFIED",
  "explanation_quality": "GOOD",
  "confidence": 0.99,
  "audit_report": "Calculated p = mv — verified option a with 10 kg m/s.",
  "reasoning": "Standard formula — clear and direct.",
  "explanation": {
    "key_point": "Linear momentum is mass times velocity — p = mv.",
    "body": "Step 1: Identify given values — m = 2kg, v = 5m/s. Step 2: Multiply — p = 10.",
    "trap": "Distractor b is 2.5 kg m/s — calculated by division instead of multiplication."
  }
}"""
    response, marks = parse_and_snap_response(raw_ai, stem)
    # Assert zero em dashes remain anywhere
    assert "—" not in response.audit_report
    assert "—" not in response.reasoning
    assert "—" not in response.explanation.key_point
    assert "—" not in response.explanation.body
    assert "—" not in response.explanation.trap
    assert "--" not in response.audit_report
    assert "verified option a" in response.audit_report


