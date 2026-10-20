"""ai-verify as a task: judged rows in, verdicts recorded, nothing promoted early."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from utmelab_bank.config import Config
from utmelab_bank.model.base import now_iso
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.task import run_task
from utmelab_bank.task.ai.verify import AiVerify
from utmelab_bank.task.ai.verify_prompt import build_verify_prompt
from utmelab_bank.task.ai.verify_schema import (
    VERIFY_SCOPES,
    VerifyOutput,
    VerifyResult,
    verify_output_from_text,
)
from utmelab_bank.task.ai.verify_tasks import verify_question


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
        "id": "q_verify_1",
        "source_url": "https://myschool.ng/x#1",
        "source_item_id": "1",
        "payload_hash": hashlib.sha256(b"q_verify_1").hexdigest(),
        "exam": "jamb",
        "subject": "physics",
        "year": 2025,
        "source": "claimed_paper",
        "text": "Which of the following is a noble gas?",
        "inline": "[]",
        "options": json.dumps(opts, separators=(",", ":")),
        "answer": "A",
        "subtopic_id": "noble-gases",
        "section": None,
        "passage_id": None,
        "explanation": '{"key_point": {"text": "Noble gases are inert.", "inline": []}, "body": {"text": "Argon has a full outer shell.", "inline": []}, "trap": {"text": "Oxygen is reactive.", "inline": []}}',
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
# verify_schema.py: strict on verdict, tolerant on scope
# ---------------------------------------------------------------------------


def test_verdict_pass_and_fail_only():
    assert VerifyOutput.model_validate({"verdict": "PASS"}).verdict == "pass"
    assert VerifyOutput.model_validate({"verdict": "fail"}).verdict == "fail"
    with pytest.raises(ValidationError):
        VerifyOutput.model_validate({"verdict": "maybe"})


def test_scope_whitelisted_falls_back_to_answer_explanation():
    out = VerifyOutput.model_validate({"verdict": "pass", "scope": ["answer", "bogus"]})
    assert out.scope == ["answer"]
    out = VerifyOutput.model_validate({"verdict": "pass", "scope": ["bogus"]})
    assert out.scope == ["answer", "explanation"]
    out = VerifyOutput.model_validate({"verdict": "pass"})
    assert out.scope == ["answer", "explanation"]


def test_verify_scopes_cover_the_contract():
    assert {"answer", "explanation", "passage"} <= VERIFY_SCOPES


def test_garbage_raises():
    with pytest.raises(ValueError):
        verify_output_from_text("", lambda _t: {})
    with pytest.raises(ValueError):
        verify_output_from_text("no json here", lambda _t: "not a dict")


def test_verify_result_from_model_output():
    out = VerifyOutput(
        verdict="pass",
        scope=["answer", "explanation"],
        confidence=0.9,
        reasoning="evidenced",
    )
    r = VerifyResult.from_model_output("q_1", out)
    assert r.verdict == "pass"
    assert r.scope == ["answer", "explanation"]
    assert r.confidence == 0.9


def test_prompt_quotes_stem_answer_and_explanation():
    prompt = build_verify_prompt(
        "Which of the following is a noble gas?",
        ["Argon", "Oxygen", "Iron", "Sodium"],
        "A",
        "Noble gases are inert.",
        "Argon has a full outer shell.",
        "Oxygen is reactive.",
        "noble-gases",
    )
    assert "Which of the following is a noble gas?" in prompt
    assert "CLAIMED ANSWER: A" in prompt
    assert "Noble gases are inert." in prompt
    assert "CLAIMED SUBTOPIC: noble-gases" in prompt


def test_prompt_includes_the_passage_when_one_is_given():
    prompt = build_verify_prompt(
        "According to the passage, why do birds call?",
        ["To feed", "To keep the flock together"],
        "B",
        "Calls keep the flock together.",
        "The passage says so.",
        "Feeding is a distractor.",
        "comprehension",
        passage="Birds call at dawn to keep the flock together.",
    )
    assert "PASSAGE:" in prompt
    assert "keep the flock together" in prompt
    assert "passage" in prompt.split("SCOPE:")[1]


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


async def test_verify_question_pass():
    provider = _FakeProvider(
        '{"verdict": "pass", "scope": ["answer", "explanation"], '
        '"confidence": 0.9, "reasoning": "evidenced"}'
    )
    result = await verify_question(
        provider, "q_1", "stem", ["A)"], "A", "kp", "body", "trap", "sub"
    )
    assert result.error is None
    assert result.verdict == "pass"


async def test_verify_question_fail_is_data_not_error():
    provider = _FakeProvider(
        '{"verdict": "fail", "scope": ["answer"], "confidence": 0.8, "reasoning": "key is B"}'
    )
    result = await verify_question(
        provider, "q_1", "stem", ["A)"], "A", "kp", "body", "trap", "sub"
    )
    assert result.error is None
    assert result.verdict == "fail"


async def test_verify_question_retries_then_errors():
    provider = _FakeProvider("not json at all")
    result = await verify_question(provider, "q_1", "stem", [], "A", "", "", "", "")
    assert result.error is not None
    assert "ValueError" in result.error


async def test_verify_gives_the_model_the_bank_passage(
    store: Store, config: Config, monkeypatch: object
) -> None:
    import utmelab_bank.task.ai.verify as verify_module

    provider = _FakeProvider(
        '{"verdict": "pass", "scope": ["answer", "explanation", "passage"], '
        '"confidence": 0.9, "reasoning": "evidenced"}'
    )
    monkeypatch.setattr(
        verify_module, "build_provider", lambda _cfg, _eng="opencode", **_kw: provider
    )

    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [_question_row(passage_id="p_1")])
    await repo.insert_many("passages", [_passage()])

    result = await run_task(AiVerify(), config, repo, logical="questions")

    assert result.run.succeeded == 1
    assert "Birds call at dawn to keep the flock together." in provider.prompts[0]
    verif = (await repo.rows("verifications", "id=v_q_verify_1_verify"))[0]
    assert "passage" in json.loads(verif["scope"])
