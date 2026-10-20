import pytest

from utmetag.jsonio import extract_json
from utmetag.schema import ModelOutput, TagResult, model_output_from_text


def test_quality_normalized_to_upper():
    assert ModelOutput.model_validate({"explanation_quality": "good"}).explanation_quality == "GOOD"


def test_quality_invalid_becomes_unknown():
    assert ModelOutput.model_validate({"explanation_quality": "stellar"}).explanation_quality == "UNKNOWN"


def test_quality_none_becomes_unknown():
    assert ModelOutput.model_validate({"explanation_quality": None}).explanation_quality == "UNKNOWN"


def test_confidence_clamped_high():
    assert ModelOutput.model_validate({"confidence": 5}).confidence == 1.0


def test_confidence_clamped_low():
    assert ModelOutput.model_validate({"confidence": -3}).confidence == 0.0


def test_confidence_non_numeric():
    assert ModelOutput.model_validate({"confidence": "n/a"}).confidence == 0.0


def test_empty_underline_dropped():
    out = ModelOutput.model_validate({"underline": {"word": "", "start": 0, "len": 0}})
    assert out.underline is None


def test_null_underline_ok():
    assert ModelOutput.model_validate({"underline": None}).underline is None


def test_missing_fields_use_defaults():
    out = ModelOutput.model_validate({})
    assert out.subtopic_slug is None
    assert out.answer_correct is False
    assert out.confidence == 0.0
    assert out.reasoning == ""


def test_from_text_fenced():
    out = model_output_from_text('```json\n{"answer_correct": true}\n```', extract_json)
    assert out.answer_correct is True


def test_from_text_empty_raises():
    with pytest.raises(ValueError):
        model_output_from_text("   ", extract_json)


def test_from_text_rejects_non_object():
    with pytest.raises(ValueError):
        model_output_from_text("[1, 2, 3]", extract_json)


def test_tagresult_from_output():
    out = ModelOutput.model_validate({
        "subtopic_slug": "surds",
        "underline": {"word": "fox", "start": 3, "len": 3},
        "answer_correct": True,
        "explanation_quality": "good",
        "confidence": 0.9,
    })
    r = TagResult.from_model_output("q1", out)
    assert r.question_id == "q1"
    assert r.assigned_subtopic == "surds"
    assert r.underline_word == "fox"
    assert r.underline_start == 3
    assert r.underline_len == 3
    assert r.answer_verified is True
    assert r.explanation_quality == "GOOD"
    assert r.confidence == 0.9
    assert r.error is None


def test_tagresult_to_dict_roundtrip():
    r = TagResult(question_id="q1", assigned_subtopic="surds")
    d = r.to_dict()
    assert d["question_id"] == "q1"
    assert d["assigned_subtopic"] == "surds"
    assert set(d) == {
        "question_id", "assigned_subtopic", "underline_word", "underline_start",
        "underline_len", "answer_verified", "explanation_quality", "confidence",
        "reasoning", "error",
    }
