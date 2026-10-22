import json

from helpers import FakeProvider, make_question, run

from utmetag.schema import QuestionInput, SubtopicInfo, TopicInfo
from utmetag.tasks import tag_question

SUBS = [SubtopicInfo(slug="surds", topic="algebra", name="Surds", objectives=[])]
TOPICS = [TopicInfo(slug="algebra", name="Algebra", subject="mathematics", exam="JAMB", objectives=[])]


def _q(stem: str = "the quick brown fox") -> QuestionInput:
    d = make_question("q1", stem=stem)
    return QuestionInput(**{k: d[k] for k in (
        "id", "exam", "subject", "year", "source", "text", "options", "answer",
        "subtopic_id", "explanation", "marks", "difficulty",
    )})


def _reply(**over):
    base = {"subtopic_slug": "surds", "answer_correct": True,
            "explanation_quality": "GOOD", "confidence": 0.9, "reasoning": "ok"}
    base.update(over)
    return json.dumps(base)


def test_snaps_wrong_underline_offset():
    provider = FakeProvider([_reply(underline={"word": "brown", "start": 0, "len": 3})])
    result = run(tag_question(provider, _q(), SUBS, TOPICS))
    assert result.underline_word == "brown"
    assert (result.underline_start, result.underline_len) == (10, 5)


def test_keeps_correct_underline_offset():
    provider = FakeProvider([_reply(underline={"word": "quick", "start": 4, "len": 5})])
    result = run(tag_question(provider, _q(), SUBS, TOPICS))
    assert (result.underline_start, result.underline_len) == (4, 5)


def test_drops_underline_word_absent_from_stem():
    provider = FakeProvider([_reply(underline={"word": "zebra", "start": 0, "len": 5})])
    result = run(tag_question(provider, _q(), SUBS, TOPICS))
    assert result.underline_word is None
    assert result.error is None


def test_null_underline_is_kept():
    provider = FakeProvider([_reply(underline=None)])
    result = run(tag_question(provider, _q(), SUBS, TOPICS))
    assert result.underline_word is None


def test_retries_parse_failure_then_succeeds():
    provider = FakeProvider(["this is not json", _reply(subtopic_slug="surds")])
    result = run(tag_question(provider, _q(), SUBS, TOPICS, parse_retries=1, parse_backoff=0))
    assert result.error is None
    assert result.assigned_subtopic == "surds"
    assert len(provider.calls) == 2


def test_parse_failure_twice_returns_error():
    provider = FakeProvider(["nope", "still nope"])
    result = run(tag_question(provider, _q(), SUBS, TOPICS, parse_retries=1, parse_backoff=0))
    assert result.error is not None
    assert result.question_id == "q1"


def test_transport_error_returns_error_without_retry():
    provider = FakeProvider([RuntimeError("boom")])
    result = run(tag_question(provider, _q(), SUBS, TOPICS))
    assert result.error is not None
    assert "boom" in result.error
    assert len(provider.calls) == 1


def test_quality_and_confidence_propagate():
    provider = FakeProvider([_reply(explanation_quality="partial", confidence=0.5)])
    result = run(tag_question(provider, _q(), SUBS, TOPICS))
    assert result.explanation_quality == "PARTIAL"
    assert result.confidence == 0.5
    assert result.answer_verified is True


def test_calls_provider_once_on_success():
    provider = FakeProvider([_reply()])
    run(tag_question(provider, _q(), SUBS, TOPICS))
    assert len(provider.calls) == 1
    assert "the quick brown fox" in provider.calls[0]
