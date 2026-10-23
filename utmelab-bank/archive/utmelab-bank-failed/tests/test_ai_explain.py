"""ai-explain as a task: DB rows in, explanation stamped + verification inserted."""

from __future__ import annotations

import json
from typing import Any

import pytest

from utmelab_bank.config import Config
from utmelab_bank.model.base import now_iso
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.task import run_task
from utmelab_bank.task.ai.explain import AiExplain
from utmelab_bank.task.ai.explain_prompt import build_explain_prompt
from utmelab_bank.task.ai.explain_schema import (
    ExplainOutput,
    ExplainResult,
    explain_output_from_text,
)
from utmelab_bank.task.ai.explain_tasks import explain_question


class FakeReference:
    """Production is empty; the explain flow can run without a taxonomy."""

    async def subtopic(self, slug: str) -> None:
        return None

    async def topic(self, slug: str) -> None:
        return None


def _question_row(**over: Any) -> dict[str, Any]:
    import hashlib
    import json

    stamp = now_iso()
    opts = [
        {"id": "A", "text": {"text": "Argon", "inline": []}},
        {"id": "B", "text": {"text": "Oxygen", "inline": []}},
        {"id": "C", "text": {"text": "Iron", "inline": []}},
        {"id": "D", "text": {"text": "Sodium", "inline": []}},
    ]
    row: dict[str, Any] = {
        "id": "q_explain_1",
        "source_url": "https://myschool.ng/x#1",
        "source_item_id": "1",
        "payload_hash": hashlib.sha256(b"q_explain_1").hexdigest(),
        "exam": "jamb",
        "subject": "physics",
        "year": 2025,
        "source": "claimed_paper",
        "text": "Which of the following is a noble gas?",
        "inline": "[]",
        "options": json.dumps(opts, separators=(",", ":")),
        "answer": "A",
        "subtopic_id": None,
        "section": None,
        "passage_id": None,
        "explanation": None,
        "marks": 1.0,
        "difficulty": 3,
        "content_hash": "h" * 64,
        "fingerprint": None,
        "stem_key": None,
        "gate_status": "pass",
        "gate_reason": None,
        "attempts": 0,
        "error": None,
        "next_retry_at": None,
        "run_id": "r_setup",
        "created_at": stamp,
        "updated_at": stamp,
    }
    row.update(over)
    return row


def _passage() -> dict[str, Any]:
    stamp = now_iso()
    return {
        "id": "p_1",
        "exam": "jamb",
        "subject": "physics",
        "year": 2025,
        "kind": "Comprehension",
        "title": None,
        "author": None,
        "text": "Birds call at dawn to keep the flock together.",
        "inline": "[]",
        "created_at": stamp,
        "updated_at": stamp,
    }


# ---------------------------------------------------------------------------
# explain_schema.py: validators + parse
# ---------------------------------------------------------------------------


def test_confidence_is_clamped():
    assert ExplainOutput.model_validate({"confidence": 9.9}).confidence == 1.0
    assert ExplainOutput.model_validate({"confidence": -1.0}).confidence == 0.0
    assert ExplainOutput.model_validate({"confidence": "junk"}).confidence == 0.0


def test_empty_response_raises():
    with pytest.raises(ValueError):
        explain_output_from_text("", lambda _t: {})
    with pytest.raises(ValueError):
        explain_output_from_text("no json here", lambda _t: "not a dict")


def test_explain_result_from_model_output():
    out = ExplainOutput(
        key_point="Noble gases are inert.",
        body="Argon has a full outer shell.",
        trap="Oxygen is reactive, so it cannot be noble.",
        confidence=0.9,
    )
    r = ExplainResult.from_model_output("q_explain_1", out)
    assert r.question_id == "q_explain_1"
    assert r.key_point == "Noble gases are inert."
    assert r.body == "Argon has a full outer shell."
    assert r.trap == "Oxygen is reactive, so it cannot be noble."
    assert r.confidence == 0.9


# ---------------------------------------------------------------------------
# explain_prompt.py: stem + options + answer rendered
# ---------------------------------------------------------------------------


def test_prompt_includes_the_syllabus_when_it_is_given():
    prompt = build_explain_prompt(
        "Which of the following is a noble gas?",
        ["Argon", "Oxygen"],
        "A",
        topic={"name": "Periodicity", "objectives": ["Explain periodic trends"]},
        subtopic={"name": "Noble Gases", "objectives": ["State the noble gas group"]},
    )
    assert "SYLLABUS CONTEXT:" in prompt
    assert "Periodicity" in prompt
    assert "Noble Gases" in prompt


def test_prompt_includes_stem_options_answer():
    prompt = build_explain_prompt(
        "Which of the following is a noble gas?",
        ["Argon", "Oxygen", "Iron", "Sodium"],
        "A",
    )
    assert "Which of the following is a noble gas?" in prompt
    assert "Argon" in prompt
    assert "Oxygen" in prompt
    assert "CORRECT ANSWER: A" in prompt


def test_prompt_includes_the_passage_when_one_is_given():
    prompt = build_explain_prompt(
        "According to the passage, why do birds call?",
        ["To feed", "To keep the flock together"],
        "B",
        passage="Birds call at dawn to keep the flock together.",
    )
    assert "PASSAGE:" in prompt
    assert "keep the flock together" in prompt


# ---------------------------------------------------------------------------
# explain_tasks.py: fake provider, parse-retry, transport failure
# ---------------------------------------------------------------------------


class _FakeProvider:
    def __init__(self, reply: str | None = None) -> None:
        self.reply = reply
        self.calls = 0
        self.prompts: list[str] = []
        self.name = "fake"

    async def complete(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if self.reply is None:
            raise OSError("network down")
        return self.reply

    async def aclose(self) -> None:
        return None


async def test_explain_question_returns_result():
    provider = _FakeProvider(
        '{"key_point": "Noble gases are inert.", "body": "Argon has a full outer shell.", '
        '"trap": "Oxygen is reactive.", "confidence": 0.9}'
    )
    result = await explain_question(provider, "q_1", "Which gas?", ["A)", "B)"], "A")
    assert result.error is None
    assert result.key_point == "Noble gases are inert."
    assert result.body == "Argon has a full outer shell."
    assert result.trap == "Oxygen is reactive."
    assert result.confidence == 0.9


async def test_explain_question_retries_then_errors():
    provider = _FakeProvider("not json at all")
    result = await explain_question(provider, "q_1", "stem", [], "A")
    assert result.error is not None
    assert "ValueError" in result.error


async def test_explain_question_transport_failure_errors():
    provider = _FakeProvider(None)
    result = await explain_question(provider, "q_1", "stem", [], "A")
    assert result.error is not None
    assert "network down" in result.error


# ---------------------------------------------------------------------------
# explain.py: task framing — selector skips, stamp + verification
# ---------------------------------------------------------------------------


async def test_explain_stamps_and_verifies(
    store: Store, config: Config, monkeypatch: object
) -> None:
    import utmelab_bank.task.ai.explain as explain_module

    monkeypatch.setattr(
        explain_module,
        "build_provider",
        lambda _cfg, _eng="opencode", **_kw: _FakeProvider(
            '{"key_point": "Noble gases are inert.", "body": "Argon has a full outer shell.", '
            '"trap": "Oxygen is reactive.", "confidence": 0.8}'
        ),
    )

    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [_question_row()])

    result = await run_task(
        AiExplain(), config, repo, logical="questions", reference=FakeReference()
    )

    assert result.run.succeeded == 1
    assert result.run.failed == 0
    updated = (await repo.rows("questions", "id=q_explain_1"))[0]
    assert updated["explanation"] is not None
    expl = json.loads(updated["explanation"])
    assert expl["body"]["text"].startswith("Argon")
    verif = (await repo.rows("verifications", "id=v_q_explain_1_explain"))[0]
    assert verif["kind"] == "ai_explain"
    assert verif["verdict"] == "pass"
    assert verif["scope"] == '["answer", "explanation"]'
    assert verif["content_hash"] == "h" * 64


async def test_explain_gives_the_model_the_bank_passage(
    store: Store, config: Config, monkeypatch: object
) -> None:
    import utmelab_bank.task.ai.explain as explain_module

    provider = _FakeProvider('{"key_point": "k", "body": "b", "trap": "t"}')
    monkeypatch.setattr(
        explain_module, "build_provider", lambda _cfg, _eng="opencode", **_kw: provider
    )

    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [_question_row(passage_id="p_1")])
    await repo.insert_many("passages", [_passage()])

    await run_task(AiExplain(), config, repo, logical="questions", reference=FakeReference())

    assert "Birds call at dawn to keep the flock together." in provider.prompts[0]


async def test_explain_skips_already_explained(    store: Store, config: Config, monkeypatch: object
) -> None:
    import utmelab_bank.task.ai.explain as explain_module

    monkeypatch.setattr(
        explain_module,
        "build_provider",
        lambda _cfg, _eng="opencode", **_kw: _FakeProvider(
            '{"key_point": "x", "body": "y", "trap": "z"}'
        ),
    )

    repo = Repository(store, lane="work")
    await repo.insert_many(
        "questions",
        [
            _question_row(
                explanation='{"key_point": {"text": "k", "inline": []}, "body": {"text": "b", "inline": []}, "trap": {"text": "t", "inline": []}}'
            )
        ],
    )

    result = await run_task(
        AiExplain(), config, repo, logical="questions", reference=FakeReference()
    )

    assert result.run.skipped == 1
    assert result.run.failed == 0


async def test_explain_failure_is_retryable(
    store: Store, config: Config, monkeypatch: object
) -> None:
    import utmelab_bank.task.ai.explain as explain_module

    monkeypatch.setattr(
        explain_module,
        "build_provider",
        lambda _cfg, _eng="opencode", **_kw: _FakeProvider(None),
    )

    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [_question_row()])

    result = await run_task(
        AiExplain(), config, repo, logical="questions", reference=FakeReference()
    )

    assert result.run.failed == 1
    assert result.run.succeeded == 0
    updated = (await repo.rows("questions", "id=q_explain_1"))[0]
    assert updated["error"] is not None
    assert updated["next_retry_at"] is not None
