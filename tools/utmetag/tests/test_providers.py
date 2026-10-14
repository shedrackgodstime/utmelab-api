import pytest
from helpers import run

from utmetag.providers import build_provider
from utmetag.providers.mock import MockProvider
from utmetag.providers.opencode import OpenCodeProvider

SUBTopic_PROMPT = (
    "Question: What is a surd?\n\nOPTIONS:\n  A) x\n\n"
    "AVAILABLE SUBTOPICS (choose exactly one, or null if none fit):\n"
    "  - surds: Surds (topic: algebra)\n"
    "  - indices: Indices (topic: algebra)\n"
)


def test_extract_text_from_ndjson_events():
    raw = "\n".join([
        '{"type":"step_start"}',
        '{"type":"text","part":{"text":"Hello "}}',
        '{"type":"text","part":{"text":"world"}}',
        '{"type":"step_finish"}',
    ])
    assert OpenCodeProvider.extract_text(raw) == "Hello world"


def test_extract_text_fallback_strips_banner():
    raw = "> opencode/space-bunny-free\nHere is the answer"
    assert OpenCodeProvider.extract_text(raw) == "Here is the answer"


def test_extract_text_ignores_non_json_noise():
    raw = "noise line\n" + '{"type":"text","part":{"text":"ok"}}'
    assert OpenCodeProvider.extract_text(raw) == "ok"


def test_opencode_provider_name():
    p = OpenCodeProvider(model="opencode/space-bunny-free")
    assert p.name == "opencode:opencode/space-bunny-free"


def test_mock_is_deterministic():
    p = MockProvider()
    first = run(p.complete(SUBTopic_PROMPT))
    second = run(p.complete(SUBTopic_PROMPT))
    assert first == second


def test_mock_picks_subtopic_from_available_list():
    import json

    p = MockProvider()
    data = json.loads(run(p.complete(SUBTopic_PROMPT)))
    assert data["subtopic_slug"] in {"surds", "indices"}


def test_mock_picks_subtopic_when_objectives_interleaved():
    import json

    from utmetag.prompt import build_tagging_prompt
    from utmetag.schema import QuestionInput, SubtopicInfo, TopicInfo
    from helpers import make_question

    d = make_question("q1")
    question = QuestionInput(**{k: d[k] for k in (
        "id", "exam", "subject", "year", "source", "text", "options", "answer",
        "subtopic_id", "explanation", "marks", "difficulty",
    )})
    subtopics = [
        SubtopicInfo(slug="surds", topic="algebra", name="Surds", objectives=["define a surd"]),
        SubtopicInfo(slug="indices", topic="algebra", name="Indices", objectives=["apply index laws"]),
    ]
    topics = [TopicInfo(slug="algebra", name="Algebra", subject="mathematics", exam="JAMB", objectives=["x"])]
    prompt = build_tagging_prompt(question, subtopics, topics)
    data = json.loads(run(MockProvider().complete(prompt)))
    assert data["subtopic_slug"] in {"surds", "indices"}


def test_mock_detects_underline_in_stem():
    import json

    stem = "Choose the underlined word: the quick brown fox"
    prompt = f"Question: {stem}\n\nOPTIONS:\n  A) x\n"
    data = json.loads(run(MockProvider().complete(prompt)))
    underline = data["underline"]
    assert underline is not None
    assert stem[underline["start"]:underline["start"] + underline["len"]] == underline["word"]


def test_mock_no_underline_when_absent():
    import json

    data = json.loads(run(MockProvider().complete("Question: plain question\n\nOPTIONS:\n  A) x\n")))
    assert data["underline"] is None


def test_build_mock():
    p = build_provider("mock")
    assert p.name == "mock"


def test_build_opencode_default_model():
    p = build_provider("opencode")
    assert p.name == "opencode:opencode/space-bunny-free"


def test_build_opencode_model_override():
    p = build_provider("opencode", model="opencode/minimax-m2-free")
    assert p.name == "opencode:opencode/minimax-m2-free"


def test_build_unknown_engine_exits():
    with pytest.raises(SystemExit):
        build_provider("bogus")


def test_no_http_engine_available():
    with pytest.raises(SystemExit):
        build_provider("http")
