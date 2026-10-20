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


async def _repo_with(store: Store, rows: list, passages: list | None = None) -> Repository:
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", rows)
    if passages:
        await repo.insert_many("passages", passages)
    return repo


def _passage(**over) -> dict:
    stamp = now_iso()
    passage = {
        "id": "p_1",
        "exam": "jamb",
        "subject": "physics",
        "year": 2025,
        "kind": "Comprehension",
        "title": None,
        "author": None,
        "text": "A body at rest stays at rest unless a force acts on it.",
        "inline": "[]",
        "created_at": stamp,
        "updated_at": stamp,
    }
    passage.update(over)
    return passage


class FakeReference:
    """The production taxonomy, without a production database."""

    async def topics_and_subtopics(
        self, subject: str, exam: str
    ) -> tuple[list[dict], list[dict]]:
        return (
            [
                {
                    "slug": "alkali-metals",
                    "topic": "periodicity",
                    "name": "Alkali Metals",
                    "objectives": [],
                },
                {
                    "slug": "noble-gases",
                    "topic": "periodicity",
                    "name": "Noble Gases",
                    "objectives": [],
                },
            ],
            [
                {
                    "slug": "periodicity",
                    "name": "Periodicity",
                    "subject": subject,
                    "exam": exam,
                    "objectives": [],
                }
            ],
        )

    async def subtopic(self, slug: str):
        if slug != "alkali-metals":
            return None
        return {
            "slug": slug,
            "topic": "periodicity",
            "name": "Alkali Metals",
            "objectives": [],
            "subject": "physics",
            "exam": "JAMB",
        }

    async def topic(self, slug: str):
        return None

    async def subject(self, slug: str, exam: str):
        return {"slug": slug, "exam": exam, "name": "Physics", "is_compulsory": 0}


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
    assert json.loads(written["scope"]) == ["answer", "explanation"]
    verifications = await repo.rows("verifications", "all", limit=None)
    assert is_verified(verifications, _row()) is True


async def test_a_passaged_row_needs_a_passage_pass(store: Store) -> None:
    row = _row(passage_id="p_1")
    repo = await _repo_with(store, [row], passages=[_passage()])

    written = await write_verification(repo, row, by="reviewer")

    assert json.loads(written["scope"]) == ["answer", "explanation", "passage"]
    verifications = await repo.rows("verifications", "all", limit=None)
    assert is_verified(verifications, row) is True


async def test_answer_and_explanation_alone_do_not_verify_a_passaged_row() -> None:
    row = _row(passage_id="p_1")
    verification = {
        "id": "v_1",
        "question_id": "q_rev_1",
        "kind": "human",
        "verdict": "pass",
        "scope": json.dumps(["answer", "explanation"]),
        "verifier": "reviewer",
        "detail": None,
        "content_hash": "h" * 64,
        "created_at": now_iso(),
    }

    assert is_verified([verification], row) is False


async def test_a_missing_bank_passage_refuses_verification(store: Store) -> None:
    row = _row(passage_id="p_missing")
    repo = await _repo_with(store, [row])

    with pytest.raises(Exception, match="passage_missing"):
        await write_verification(repo, row, by="reviewer")


async def test_bundle_reads_the_passage_from_the_bank_lane(store: Store) -> None:
    row = _row(passage_id="p_1")
    repo = await _repo_with(store, [row], passages=[_passage()])

    b = await bundle(repo, FakeReference(), "q_rev_1")

    assert b["passage"]["id"] == "p_1"
    assert b["passage"]["text"].startswith("A body at rest")
    assert "passage_missing" not in b["flags"]


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
    changed = await set_fields(repo, _row(), reference=FakeReference(), subtopic="alkali-metals")
    assert changed["subtopic_id"] == "alkali-metals"
    updated = (await repo.rows("questions", "id=q_rev_1"))[0]
    assert updated["subtopic_id"] == "alkali-metals"


async def test_set_underline_must_match_the_stem(store: Store) -> None:
    repo = await _repo_with(store, [_row()])
    with pytest.raises(Exception, match="substring"):
        await set_fields(repo, _row(), reference=FakeReference(), underline="not in the stem")


async def test_bundle_and_render_cover_a_row(store: Store) -> None:
    repo = await _repo_with(store, [_row()])
    b = await bundle(repo, FakeReference(), "q_rev_1")
    assert b["verified"] is False
    text = render_human(b)
    assert "q_rev_1" in text
    assert "Argon" in text


async def test_set_underline_writes_a_mark_and_restamps_the_identity(store: Store) -> None:
    repo = await _repo_with(store, [_row()])
    phrase = "noble gas"

    changed = await set_fields(repo, _row(), reference=FakeReference(), underline=phrase)

    marks = json.loads(changed["inline"])
    assert marks == [
        {"kind": "underline", "start": _row()["text"].find(phrase), "len": len(phrase)}
    ]
    assert changed["content_hash"] != "h" * 64
    assert len(changed["content_hash"]) == 64

    saved = (await repo.rows("questions", "id=q_rev_1"))[0]
    assert json.loads(saved["inline"]) == marks
    assert saved["content_hash"] == changed["content_hash"]


async def test_set_underline_replaces_a_previous_mark(store: Store) -> None:
    row = _row(inline='[{"kind": "underline", "start": 0, "len": 5}]')
    repo = await _repo_with(store, [row])

    changed = await set_fields(repo, row, reference=FakeReference(), underline="noble gas")

    assert [mark["kind"] for mark in json.loads(changed["inline"])] == ["underline"]
    assert json.loads(changed["inline"])[0]["start"] == row["text"].find("noble gas")


async def test_set_underline_survives_a_broken_inline_column(store: Store) -> None:
    row = _row(inline="{not json")
    repo = await _repo_with(store, [row])

    changed = await set_fields(repo, row, reference=FakeReference(), underline="noble gas")

    assert [mark["kind"] for mark in json.loads(changed["inline"])] == ["underline"]


async def test_set_marks_difficulty_and_section(store: Store) -> None:
    repo = await _repo_with(store, [_row()])

    changed = await set_fields(repo, _row(), reference=FakeReference(), marks=2.0, difficulty=5, section="A")

    assert changed["marks"] == 2.0
    assert changed["difficulty"] == 5
    assert changed["section"] == "A"
    saved = (await repo.rows("questions", "id=q_rev_1"))[0]
    assert (saved["marks"], saved["difficulty"], saved["section"]) == (2.0, 5, "A")


async def test_set_refuses_marks_and_difficulty_out_of_range(store: Store) -> None:
    repo = await _repo_with(store, [_row()])

    with pytest.raises(Exception, match="marks look wrong"):
        await set_fields(repo, _row(), reference=FakeReference(), marks=-1.0)
    with pytest.raises(Exception, match="difficulty is 1-5"):
        await set_fields(repo, _row(), reference=FakeReference(), difficulty=6)


async def test_set_a_passage_that_exists(store: Store) -> None:
    repo = await _repo_with(store, [_row()], passages=[_passage()])
    changed = await set_fields(repo, _row(), reference=FakeReference(), passage="p_1")

    assert changed["passage_id"] == "p_1"


async def test_set_refuses_a_passage_that_does_not_exist(store: Store) -> None:
    repo = await _repo_with(store, [_row()])

    with pytest.raises(Exception, match="no passage"):
        await set_fields(repo, _row(), reference=FakeReference(), passage="p_missing")


async def test_set_refuses_a_subtopic_that_is_not_catalogued(store: Store) -> None:
    repo = await _repo_with(store, [_row()])

    with pytest.raises(Exception, match="no subtopic"):
        await set_fields(repo, _row(), reference=FakeReference(), subtopic="nope")


async def test_set_refuses_a_subtopic_under_another_exam(store: Store) -> None:
    repo = await _repo_with(store, [_row(exam="waec")])

    with pytest.raises(Exception, match="under waec/physics"):
        await set_fields(repo, _row(exam="waec"), reference=FakeReference(), subtopic="alkali-metals")


async def test_set_a_dry_run_reports_without_writing(store: Store) -> None:
    repo = await _repo_with(store, [_row()])

    changed = await set_fields(repo, _row(), reference=FakeReference(), marks=2.0, dry_run=True)

    assert changed == {"marks": 2.0}
    saved = (await repo.rows("questions", "id=q_rev_1"))[0]
    assert saved["marks"] == 1.0
