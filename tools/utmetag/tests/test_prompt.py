from helpers import make_question

from utmetag.prompt import build_tagging_prompt
from utmetag.schema import QuestionInput, SubtopicInfo, TopicInfo


def _q(**kw) -> QuestionInput:
    d = make_question("q1", **kw)
    return QuestionInput(**{k: d[k] for k in (
        "id", "exam", "subject", "year", "source", "text", "options", "answer",
        "subtopic_id", "explanation", "marks", "difficulty",
    )})


SUBS = [
    SubtopicInfo(slug="surds", topic="algebra", name="Surds", objectives=[]),
    SubtopicInfo(slug="indices", topic="algebra", name="Indices", objectives=[]),
]
TOPICS = [TopicInfo(slug="algebra", name="Algebra", subject="mathematics", exam="JAMB", objectives=[])]


def test_prompt_includes_stem_options_answer():
    prompt = build_tagging_prompt(_q(stem="What is 1+1?", answer="A"), SUBS, TOPICS)
    assert "What is 1+1?" in prompt
    assert "A) 1" in prompt
    assert "CORRECT ANSWER: A" in prompt


def test_prompt_lists_subtopics_and_topics():
    prompt = build_tagging_prompt(_q(), SUBS, TOPICS)
    assert "- surds: Surds (topic: algebra)" in prompt
    assert "- indices: Indices (topic: algebra)" in prompt
    assert "- algebra: Algebra" in prompt


def test_prompt_missing_explanation_marker():
    prompt = build_tagging_prompt(_q(explanation=None), SUBS, TOPICS)
    assert "EXPLANATION:\nMISSING" in prompt


def test_prompt_null_trap_does_not_crash():
    explanation = {
        "key_point": {"text": "the key point"},
        "body": {"text": "the body"},
        "trap": None,
    }
    prompt = build_tagging_prompt(_q(explanation=explanation), SUBS, TOPICS)
    assert "Key point: the key point" in prompt
    assert "Body: the body" in prompt
    assert "Trap: " in prompt


def test_prompt_all_null_explanation_parts_is_missing():
    explanation = {"key_point": None, "body": None, "trap": None}
    prompt = build_tagging_prompt(_q(explanation=explanation), SUBS, TOPICS)
    assert "MISSING" in prompt
