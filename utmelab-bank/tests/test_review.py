"""The review workbench: show/next/verify/set/stats over the work lane."""

from __future__ import annotations

import json

import pytest

from utmelab_bank.model.base import now_iso
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.task.review import (
    bundle,
    gate_flags,
    is_verified,
    next_id,
    render_human,
    set_fields,
    write_verification,
)


def _row(**over) -> dict:
    import hashlib
    import json

    stamp = now_iso()
    opts = [
        {"id": "A", "text": {"text": "Argon", "inline": []}},
        {"id": "B", "text": {"text": "Oxygen", "inline": []}},
        {"id": "C", "text": {"text": "Iron", "inline": []}},
        {"id": "D", "text": {"text": "Sodium", "inline": []}},
    ]
    row = {
        "id": "q_rev_1",
        "source_url": "https://myschool.ng/x#1",
        "source_item_id": "1",
        "payload_hash": hashlib.sha256(b"q_rev_1").hexdigest(),
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


async def _repo_with(store: Store, rows: list) -> Repository:
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", rows)
    return repo


async def test_next_id_is_the_lowest_unverified(store: Store) -> None:
    repo = await _repo_with(store, [_row(id="q_z"), _row(id="q_a"), _row(id="q_m")])
    assert await next_id(repo) == "q_a"
    assert await next_id(repo, subject="physics") == "q_a"


async def test_next_id_refuses_when_nothing_left(store: Store) -> None:
    repo = Repository(store, lane="work")
    with pytest.raises(Exception, match="no unverified"):
        await next_id(repo)


async def test_is_verified_needs_human_pass_on_current_hash(store: Store) -> None:
    repo = await _repo_with(store, [_row()])
    assert is_verified([], _row()) is False
    stamp = now_iso()
    await repo.insert_many(
        "verifications",
        [
            {
                "id": "v_1",
                "question_id": "q_rev_1",
                "kind": "ai_verify",
                "verdict": "pass",
                "scope": json.dumps(["answer", "explanation"]),
                "verifier": "opencode:x",
                "detail": None,
                "content_hash": "h" * 64,
                "created_at": stamp,
            }
        ],
    )
    verifications = await repo.rows("verifications", "all", limit=None)
    # An AI pass is signal, not verified.
    assert is_verified(verifications, _row()) is False


async def test_write_verification_appends_human_pass(store: Store) -> None:
    repo = await _repo_with(store, [_row()])
    written = await write_verification(repo, _row(), by="reviewer")
    assert written["kind"] == "human"
    assert written["verdict"] == "pass"
    assert written["content_hash"] == "h" * 64
    verifications = await repo.rows("verifications", "all", limit=None)
    assert is_verified(verifications, _row()) is True


async def test_write_verification_refuses_an_explanationless_row(store: Store) -> None:
    repo = await _repo_with(store, [_row(explanation=None)])
    with pytest.raises(Exception, match="explanation first"):
        await write_verification(repo, _row(explanation=None), by="reviewer")


async def test_write_verification_refuses_a_gate_flagged_row(store: Store) -> None:
    bad = _row(text="A.", answer="Z")
    repo = await _repo_with(store, [bad])
    assert gate_flags(bad)
    with pytest.raises(Exception, match=r"esolve first|esolved"):
        await write_verification(repo, bad, by="reviewer")


async def test_set_subtopic_and_underline_rewrite_hash(store: Store) -> None:
    repo = await _repo_with(store, [_row()])
    await repo.insert_many(
        "topics",
        [
            {
                "slug": "periodicity",
                "subject": "physics",
                "exam": "jamb",
                "name": "Periodicity",
                "ord": 1,
                "weight": None,
                "objectives": "[]",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        ],
    )
    await repo.insert_many(
        "subtopics",
        [
            {
                "slug": "alkali-metals",
                "topic": "periodicity",
                "name": "Alkali Metals",
                "ord": 1,
                "objectives": "[]",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        ],
    )
    changed = await set_fields(repo, _row(), subtopic="alkali-metals")
    assert changed["subtopic_id"] == "alkali-metals"
    updated = (await repo.rows("questions", "id=q_rev_1"))[0]
    assert updated["subtopic_id"] == "alkali-metals"


async def test_set_underline_must_match_the_stem(store: Store) -> None:
    repo = await _repo_with(store, [_row()])
    with pytest.raises(Exception, match="substring"):
        await set_fields(repo, _row(), underline="not in the stem")


async def test_bundle_and_render_cover_a_row(store: Store) -> None:
    repo = await _repo_with(store, [_row()])
    b = await bundle(repo, "q_rev_1")
    assert b["verified"] is False
    text = render_human(b)
    assert "q_rev_1" in text
    assert "Argon" in text
