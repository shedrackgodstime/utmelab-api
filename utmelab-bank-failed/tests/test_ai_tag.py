"""The ai-tag core: schema validation, prompt construction, tag + underline snap."""

from __future__ import annotations

import pytest

from utmelab_bank.task.ai import (
    ModelOutput,
    TagResult,
    build_tagging_prompt,
    extract_json,
    snap_underline,
    tag_question,
)
from utmelab_bank.task.ai.providers import MockProvider


def _question(**over: object) -> dict:
    q = {
        "id": "q_1",
        "exam": "jamb",
        "subject": "physics",
        "year": 2025,
        "source": "claimed_paper",
        "text": {"text": "Which of the following is a noble gas?", "inline": []},
        "options": [
            {"id": "A", "text": {"text": "Argon", "inline": []}},
            {"id": "B", "text": {"text": "Oxygen", "inline": []}},
            {"id": "C", "text": {"text": "Iron", "inline": []}},
            {"id": "D", "text": {"text": "Sodium", "inline": []}},
        ],
        "answer": "A",
    }
    q.update(over)
    return q


def _subtopics() -> list:
    return [
        {"slug": "noble-gases", "topic": "periodicity", "name": "Noble Gases", "objectives": []},
        {
            "slug": "alkali-metals",
            "topic": "periodicity",
            "name": "Alkali Metals",
            "objectives": [],
        },
    ]


def _topics() -> list:
    return [
        {
            "slug": "periodicity",
            "name": "Periodicity",
            "subject": "physics",
            "exam": "jamb",
            "objectives": [],
        }
    ]


# ---------------------------------------------------------------------------
# schema.py: ModelOutput validators + model_output_from_text
# ---------------------------------------------------------------------------


def test_quality_is_normalized():
    out = ModelOutput.model_validate({"explanation_quality": "good"})
    assert out.explanation_quality == "GOOD"
    out = ModelOutput.model_validate({"explanation_quality": "nonsense"})
    assert out.explanation_quality == "UNKNOWN"


def test_confidence_is_clamped():
    assert ModelOutput.model_validate({"confidence": 9.9}).confidence == 1.0
    assert ModelOutput.model_validate({"confidence": -1.0}).confidence == 0.0
    assert ModelOutput.model_validate({"confidence": "junk"}).confidence == 0.0


def test_empty_underline_is_dropped():
    out = ModelOutput.model_validate({"underline": {"word": "  ", "start": 0, "len": 0}})
    assert out.underline is None


def test_empty_response_raises():
    from utmelab_bank.task.ai.schema import model_output_from_text

    with pytest.raises(ValueError):
        model_output_from_text("", extract_json)
    with pytest.raises(ValueError):
        model_output_from_text("no json here", extract_json)


def test_tag_result_from_model_output():
    out = ModelOutput(
        subtopic_slug="surds",
        underline={"word": "cogent", "start": 24, "len": 6},
        answer_correct=True,
        explanation_quality="GOOD",
        confidence=0.9,
        reasoning="clear",
    )
    r = TagResult.from_model_output("q_1", out)
    assert r.assigned_subtopic == "surds"
    assert r.underline_word == "cogent"
    assert r.underline_start == 24
    assert r.underline_len == 6
    assert r.answer_verified is True


# ---------------------------------------------------------------------------
# prompt.py: one prompt per question, JSON output contract
# ---------------------------------------------------------------------------


def test_prompt_names_the_stem_and_the_menu():
    prompt = build_tagging_prompt(_question(), _subtopics(), _topics())
    assert "Which of the following is a noble gas?" in prompt
    assert "noble-gases" in prompt
    assert "alkali-metals" in prompt
    assert "CORRECT ANSWER: A" in prompt
    assert "EXPLANATION:\nMISSING" in prompt


def test_prompt_renders_explanation_when_present():
    q = _question(
        explanation={
            "key_point": {"text": "Noble gases are inert."},
            "body": {"text": "Full shells."},
            "trap": {"text": "Oxygen is reactive."},
        }
    )
    prompt = build_tagging_prompt(q, _subtopics(), _topics())
    assert "Key point: Noble gases are inert." in prompt
    assert "EXPLANATION:\nMISSING" not in prompt


def test_prompt_includes_the_passage_when_one_is_given():
    q = _question(passage="Birds call at dawn to keep the flock together.")
    prompt = build_tagging_prompt(q, _subtopics(), _topics())
    assert "PASSAGE:" in prompt
    assert "Birds call at dawn to keep the flock together." in prompt


# ---------------------------------------------------------------------------
# tasks.py: snap_underline + tag_question
# ---------------------------------------------------------------------------


def test_snap_keeps_a_correct_offset():
    stem = "The general was notorious for his cruelty."
    idx = stem.find("notorious")
    out = ModelOutput(underline={"word": "notorious", "start": idx, "len": 9})
    assert snap_underline(out, stem).underline is not None


def test_snap_repairs_a_wrong_offset():
    stem = "The general was notorious for his cruelty."
    out = ModelOutput(underline={"word": "notorious", "start": 999, "len": 3})
    fixed = snap_underline(out, stem)
    assert fixed.underline is not None
    assert fixed.underline.start == stem.find("notorious")
    assert fixed.underline.len == len("notorious")


def test_snap_drops_a_word_not_in_the_stem():
    stem = "What is the boiling point of pure water?"
    out = ModelOutput(underline={"word": "nonexistent_word", "start": 10, "len": 5})
    assert snap_underline(out, stem).underline is None


async def test_tag_question_uses_the_mock_provider():
    r = await tag_question(MockProvider(), _question(), _subtopics(), _topics())
    assert r.error is None
    assert r.assigned_subtopic in {"noble-gases", "alkali-metals"}


async def test_tag_question_marks_a_dead_provider_as_error():
    class Dead:
        name = "dead"

        async def complete(self, _prompt: str) -> str:
            raise OSError("network down")

        async def aclose(self) -> None:
            return None

    r = await tag_question(Dead(), _question(), _subtopics(), _topics())
    assert r.error is not None
    assert "network down" in r.error
