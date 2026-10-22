"""The AI provider seam: extract_json, MockProvider, OpenCodeProvider.extract_text.

Ported from ``tools/utmetag/tests/test_jsonio.py`` and ``test_providers.py``,
adapted to the bank's config-driven provider construction and async test mode.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utmelab_bank.config import Config, RepoRoot
from utmelab_bank.errors import AiError
from utmelab_bank.task.ai import build_provider, extract_json
from utmelab_bank.task.ai.providers import MockProvider, OpenCodeProvider

# ---------------------------------------------------------------------------
# extract_json: tolerant extraction from LLM free-text replies
# ---------------------------------------------------------------------------


def test_plain_object():
    assert extract_json('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_fenced_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_fence_without_language():
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_prose_wrapped():
    text = 'Sure! Here is the result:\n{"a": 1}\nLet me know if that helps.'
    assert extract_json(text) == {"a": 1}


def test_empty_raises():
    with pytest.raises(ValueError):
        extract_json("   ")


def test_none_raises():
    with pytest.raises(ValueError):
        extract_json(None)  # type: ignore[arg-type]


def test_no_json_raises():
    with pytest.raises(ValueError):
        extract_json("I cannot answer that.")


# ---------------------------------------------------------------------------
# OpenCodeProvider.extract_text: NDJSON events and fallback
# ---------------------------------------------------------------------------


def test_extract_text_from_ndjson_events():
    raw = "\n".join(
        [
            '{"type":"step_start"}',
            '{"type":"text","part":{"text":"Hello "}}',
            '{"type":"text","part":{"text":"world"}}',
            '{"type":"step_finish"}',
        ]
    )
    assert OpenCodeProvider.extract_text(raw) == "Hello world"


def test_extract_text_fallback_strips_banner():
    raw = "> opencode/space-bunny-free\nHere is the answer"
    assert OpenCodeProvider.extract_text(raw) == "Here is the answer"


def test_extract_text_ignores_non_json_noise():
    raw = "noise line\n" + '{"type":"text","part":{"text":"ok"}}'
    assert OpenCodeProvider.extract_text(raw) == "ok"


# ---------------------------------------------------------------------------
# MockProvider: deterministic, no network, for tests and offline runs
# ---------------------------------------------------------------------------

SUBTOPIC_PROMPT = (
    "Question: What is a surd?\n\nOPTIONS:\n  A) x\n\n"
    "AVAILABLE SUBTOPICS (choose exactly one, or null if none fit):\n"
    "  - surds: Surds (topic: algebra)\n"
    "  - indices: Indices (topic: algebra)\n"
)


async def test_mock_is_deterministic():
    p = MockProvider()
    first = await p.complete(SUBTOPIC_PROMPT)
    second = await p.complete(SUBTOPIC_PROMPT)
    assert first == second


async def test_mock_picks_subtopic_from_available_list():
    p = MockProvider()
    data = json.loads(await p.complete(SUBTOPIC_PROMPT))
    assert data["subtopic_slug"] in {"surds", "indices"}


async def test_mock_detects_underline_in_stem():
    stem = "Choose the underlined word: the quick brown fox"
    prompt = f"Question: {stem}\n\nOPTIONS:\n  A) x\n"
    data = json.loads(await MockProvider().complete(prompt))
    underline = data["underline"]
    assert underline is not None
    assert stem[underline["start"] : underline["start"] + underline["len"]] == underline["word"]


async def test_mock_no_underline_when_absent():
    data = json.loads(
        await MockProvider().complete("Question: plain question\n\nOPTIONS:\n  A) x\n")
    )
    assert data["underline"] is None


# ---------------------------------------------------------------------------
# build_provider: the factory, driven by the run's config
# ---------------------------------------------------------------------------


def _config(tmp_path: Path) -> Config:
    return Config(repo=RepoRoot(path=tmp_path), sink="db", lane="work")


def test_build_mock(tmp_path: Path):
    p = build_provider(_config(tmp_path), "mock")
    assert p.name == "mock"


def test_build_opencode_default_model(tmp_path: Path):
    p = build_provider(_config(tmp_path), "opencode")
    assert p.name == "opencode:opencode/space-bunny-free"


def test_opencode_attaches_a_figure(tmp_path: Path):
    p = OpenCodeProvider(_config(tmp_path))
    argv = p._argv("/tmp/media/fig.png")
    assert argv[argv.index("--file") + 1] == "/tmp/media/fig.png"


def test_opencode_has_no_file_without_a_figure(tmp_path: Path):
    assert "--file" not in OpenCodeProvider(_config(tmp_path))._argv()


def test_build_unknown_engine_raises(tmp_path: Path):
    with pytest.raises(AiError):
        build_provider(_config(tmp_path), "bogus")


def test_build_http_engine_raises(tmp_path: Path):
    with pytest.raises(AiError):
        build_provider(_config(tmp_path), "http")
