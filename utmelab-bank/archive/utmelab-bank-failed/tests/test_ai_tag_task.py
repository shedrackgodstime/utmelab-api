"""ai-tag as a task: DB rows in, subtopic stamped, failures retried.

The provider is monkeypatched to the mock (no network, no spend). These tests
prove the task framing — selector skips, row translation, subtopic stamping —
not the model's judgement, which ``test_ai_tag.py`` covers against the mock.
"""

from __future__ import annotations

from typing import Any

from utmelab_bank.config import Config
from utmelab_bank.model.base import now_iso
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.task import run_task
from utmelab_bank.task.ai import MockProvider, question_from_row
from utmelab_bank.task.ai.tag import AiTag


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
        "id": "q_tag_1",
        "source_url": "https://myschool.ng/x#1",
        "source_item_id": "1",
        "payload_hash": hashlib.sha256(b"q_tag_1").hexdigest(),
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


class FakeReference:
    """The production taxonomy, without a production database."""

    def __init__(self, subtopics=None, topics=None) -> None:
        self._subtopics = subtopics if subtopics is not None else [
            {
                "slug": "noble-gases",
                "topic": "periodicity",
                "name": "Noble Gases",
                "objectives": [],
            },
            {
                "slug": "alkali-metals",
                "topic": "periodicity",
                "name": "Alkali Metals",
                "objectives": [],
            },
        ]
        self._topics = topics if topics is not None else [
            {
                "slug": "periodicity",
                "name": "Periodicity",
                "subject": "physics",
                "exam": "JAMB",
                "objectives": [],
            }
        ]

    async def topics_and_subtopics(
        self, subject: str, exam: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self._subtopics, self._topics


async def test_tag_stamps_the_subtopic(store: Store, config: Config, monkeypatch: object) -> None:
    """A clean row gets the mock's subtopic stamped, run reports success."""
    import utmelab_bank.task.ai.tag as tag_module

    monkeypatch.setattr(tag_module, "build_provider", lambda _cfg, _eng="opencode": MockProvider())  # type: ignore[attr-defined]

    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [_question_row()])

    result = await run_task(AiTag(), config, repo, logical="questions", reference=FakeReference())

    assert result.run.succeeded == 1
    assert result.run.failed == 0
    updated = (await repo.rows("questions", "id=q_tag_1"))[0]
    assert updated["subtopic_id"] in {"noble-gases", "alkali-metals"}


async def test_tag_skips_a_row_that_is_already_tagged(
    store: Store, config: Config, monkeypatch: object
) -> None:
    """Idempotent: a tagged row is skipped, never re-asked."""
    import utmelab_bank.task.ai.tag as tag_module

    monkeypatch.setattr(tag_module, "build_provider", lambda _cfg, _eng="opencode": MockProvider())  # type: ignore[attr-defined]

    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [_question_row(subtopic_id="noble-gases")])

    result = await run_task(AiTag(), config, repo, logical="questions", reference=FakeReference())

    assert result.run.skipped == 1
    assert result.run.failed == 0


async def test_tag_skips_when_the_catalog_is_empty(store: Store, config: Config) -> None:
    """No subtopics for the subject: skip, not fail. The taxonomy is the gap."""
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [_question_row()])

    result = await run_task(
        AiTag(), config, repo, logical="questions", reference=FakeReference([], [])
    )

    assert result.run.skipped == 1
    assert result.run.failed == 0


def test_question_from_row_translates_lane_columns():

    q = question_from_row(_question_row())
    assert q["text"] == {"text": "Which of the following is a noble gas?", "inline": []}
    assert [o["id"] for o in q["options"]] == ["A", "B", "C", "D"]
    assert q["explanation"] is None
    assert q["passage"] == ""


def test_question_from_row_carries_the_bank_passage() -> None:
    passage = {
        "id": "p_1",
        "exam": "jamb",
        "subject": "physics",
        "year": 2025,
        "kind": "Comprehension",
        "title": None,
        "author": None,
        "text": "Birds call at dawn.",
        "inline": "[]",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    q = question_from_row(_question_row(passage_id="p_1"), passage)

    assert q["passage"] == "Birds call at dawn."


class _PromptingProvider:
    name = "fake"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return (
            '{"subtopic_slug": "noble-gases", "answer_correct": true, '
            '"explanation_quality": "GOOD", "confidence": 0.9, "reasoning": "clear"}'
        )

    async def aclose(self) -> None:
        return None


async def test_tag_gives_the_model_the_bank_passage(
    store: Store, config: Config, monkeypatch: object
) -> None:
    import utmelab_bank.task.ai.tag as tag_module

    provider = _PromptingProvider()
    monkeypatch.setattr(
        tag_module, "build_provider", lambda _cfg, _eng="opencode", **_kw: provider
    )

    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [_question_row(passage_id="p_1")])
    await repo.insert_many("passages", [_passage()])

    result = await run_task(AiTag(), config, repo, logical="questions", reference=FakeReference())

    assert result.run.succeeded == 1
    assert "Birds call at dawn to keep the flock together." in provider.prompts[0]
