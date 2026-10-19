"""Intake, and the properties the chain has to hold.

The properties are the ones a re-run depends on. Every one of them was a
question during design: what happens if the same paper is scraped twice, if
intake runs twice, if a row is refused, if promote runs on something ungated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from utmelab_bank.config import Config
from utmelab_bank.errors import TaskError
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.store.schema import ensure_schema
from utmelab_bank.task import run_task
from utmelab_bank.task.gates import MechanicalGate
from utmelab_bank.task.intake import Intake, judge_raw, refuse, work_row
from utmelab_bank.task.promote import Promote, ready_row, require_promotable

FIXTURES = Path(__file__).parent / "fixtures"


def raw_row(**overrides: Any) -> dict[str, Any]:
    """A raw row, shaped the way the api parser writes one.

    The id is the question id, because :func:`raw_row_id` is applied by the
    seeder. That mirrors the api parser, which builds the question id and lets
    the caller derive the raw key from it.
    """
    options = [
        {"id": "A", "text": {"text": "Argon", "inline": []}},
        {"id": "B", "text": {"text": "Oxygen", "inline": []}},
        {"id": "C", "text": {"text": "Iron", "inline": []}},
        {"id": "D", "text": {"text": "Sodium", "inline": []}},
    ]
    row: dict[str, Any] = {
        "id": "q_physics_2025_jamb_74347",
        "source_url": "https://myschool.ng/api/web/v1/classroom/physics?exam_type=jamb#74347",
        "source_item_id": "74347",
        "payload_hash": "a" * 64,
        "exam": "jamb",
        "subject": "physics",
        "year": 2025,
        "source": "claimed_paper",
        "text": "Which of these is a noble gas?",
        "inline": "[]",
        "options": json.dumps(options, separators=(",", ":")),
        "answer": "A",
        "subtopic_id": None,
        "section": None,
        "passage_id": None,
        "explanation": None,
        "marks": 1.0,
        "difficulty": 3,
        "content_hash": "",
        "fingerprint": None,
        "gate_status": "pending",
        "gate_reason": None,
        "attempts": 0,
        "error": None,
        "next_retry_at": None,
        "run_id": "r_scrape",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    row.update(overrides)
    return row


async def seed_raw(store: Store, rows: list[dict[str, Any]]) -> int:
    """Put rows in the raw lane. Returns how many were new."""
    from utmelab_bank.source.raw import raw_row_id

    prepared = [{**row, "id": raw_row_id(row["id"], row["payload_hash"])} for row in rows]
    return await Repository(store, lane="raw").insert_many("questions", prepared)


# ---------------------------------------------------------------------------
# The judge, before anything moves
# ---------------------------------------------------------------------------


def test_a_good_raw_row_judges_clean() -> None:
    verdict = judge_raw(raw_row())
    assert verdict.passed


def test_a_raw_row_with_a_bad_key_is_refused() -> None:
    status, reason = refuse(raw_row(answer="Z"))
    assert status == "refused"
    assert reason == "answer_not_an_option"


def test_a_raw_row_with_a_missing_figure_is_refused() -> None:
    status, reason = refuse(raw_row(text="The diagram above shows the arrangement."))
    assert status == "refused"
    assert reason == "missing_referenced_figure"


def test_refusing_a_row_states_pass_when_it_is_fine() -> None:
    assert refuse(raw_row()) == ("pass", "")


# ---------------------------------------------------------------------------
# The move
# ---------------------------------------------------------------------------


async def test_intake_moves_a_row_into_work(store: Store, config: Config) -> None:
    await seed_raw(store, [raw_row()])
    result = await run_task(Intake(), config, Repository(store, lane="work"), logical="questions")

    work = Repository(store, lane="work")
    rows = await work.rows("questions")
    assert len(rows) == 1
    assert rows[0]["gate_status"] == "pass"
    assert rows[0]["gate_reason"] is None
    assert result.run.succeeded == 1


async def test_intake_keeps_the_raw_row(store: Store, config: Config) -> None:
    """The raw row is the record of what the site said, so it survives."""
    await seed_raw(store, [raw_row()])
    await run_task(Intake(), config, Repository(store, lane="work"), logical="questions")
    assert await Repository(store, lane="raw").count("questions") == 1


async def test_intake_stamps_the_content_hash(store: Store, config: Config) -> None:
    """A row without it is silently unverified for every candidate."""
    await seed_raw(store, [raw_row()])
    await run_task(Intake(), config, Repository(store, lane="work"), logical="questions")
    rows = await Repository(store, lane="work").rows("questions")
    assert len(rows[0]["content_hash"]) == 64


async def test_intake_carries_section_across(store: Store, config: Config) -> None:
    """The pipeline's staging table had no section column, so it was always null."""
    await seed_raw(store, [raw_row(section="Section A")])
    await run_task(Intake(), config, Repository(store, lane="work"), logical="questions")
    rows = await Repository(store, lane="work").rows("questions")
    assert rows[0]["section"] == "Section A"


async def test_intake_refuses_and_records_why(store: Store, config: Config) -> None:
    await seed_raw(store, [raw_row(answer="Z")])
    await run_task(Intake(), config, Repository(store, lane="work"), logical="questions")

    assert await Repository(store, lane="work").count("questions") == 0
    raw = await Repository(store, lane="raw").rows("questions")
    assert raw[0]["gate_status"] == "refused"
    assert raw[0]["gate_reason"] == "answer_not_an_option"


async def test_a_refused_row_is_a_skip_not_a_failure(store: Store, config: Config) -> None:
    """Expected work, so it must not read as a broken run."""
    await seed_raw(store, [raw_row(answer="Z")])
    result = await run_task(Intake(), config, Repository(store, lane="work"), logical="questions")
    assert result.run.skipped == 1
    assert result.run.failed == 0
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Idempotency, which is the property a re-run depends on
# ---------------------------------------------------------------------------


async def test_intake_twice_moves_nothing_the_second_time(store: Store, config: Config) -> None:
    await seed_raw(store, [raw_row()])
    repo = Repository(store, lane="work")
    await run_task(Intake(), config, repo, logical="questions")
    second = await run_task(Intake(), config, repo, logical="questions")

    assert await repo.count("questions") == 1
    assert second.run.succeeded == 0
    assert second.run.skipped == 1


async def test_promote_twice_moves_nothing_the_second_time(store: Store, config: Config) -> None:
    await seed_raw(store, [raw_row()])
    repo = Repository(store, lane="work")
    await run_task(Intake(), config, repo, logical="questions")
    await run_task(Promote(), config, repo, where="gated", logical="questions")
    second = await run_task(Promote(), config, repo, where="gated", logical="questions")

    assert await Repository(store, lane="ready").count("questions") == 1
    assert second.run.succeeded == 0
    assert second.run.skipped == 1


async def test_re_scrape_adds_nothing_when_nothing_changed(store: Store) -> None:
    """The dedupe key is source url, item id and payload hash."""
    await seed_raw(store, [raw_row()])
    written = await seed_raw(store, [raw_row()])
    assert await Repository(store, lane="raw").count("questions") == 1
    assert written == 0


async def test_an_edited_row_appears_beside_the_old_one(store: Store) -> None:
    """Upstream drift becomes visible instead of overwriting history."""
    await seed_raw(store, [raw_row()])
    await seed_raw(store, [raw_row(payload_hash="b" * 64)])
    assert await Repository(store, lane="raw").count("questions") == 2


async def test_insert_reports_rows_landed_not_rows_sent(store: Store) -> None:
    """Reporting twelve for a batch where nothing was new is how a re-scrape
    looks like it did work."""
    repo = Repository(store, lane="work")
    assert await repo.insert_many("questions", [raw_row()]) == 1
    assert await repo.insert_many("questions", [raw_row()]) == 0


# ---------------------------------------------------------------------------
# The whole chain, on a captured payload
# ---------------------------------------------------------------------------


async def test_the_chain_runs_on_a_captured_response(store: Store, config: Config) -> None:
    fixture = FIXTURES / "myschool_physics_page1.json"
    if not fixture.is_file():
        pytest.skip("no captured response")

    from utmelab_bank.source.myschool.parser import parse_api_listing, parse_api_question

    payload = json.loads(fixture.read_text(encoding="utf-8"))
    rows = parse_api_listing(payload)
    parsed = [parse_api_question(r, exam="jamb", subject="physics", year=2025) for r in rows]

    from utmelab_bank.cli import _raw_row

    await seed_raw(store, [_raw_row(item, "r_test") for item in parsed])

    repo = Repository(store, lane="work")
    intake = await run_task(Intake(), config, repo, logical="questions")
    gate = await run_task(MechanicalGate(), config, repo, where="all", logical="questions")
    promote = await run_task(Promote(), config, repo, where="gated", logical="questions")

    assert intake.run.succeeded == len(parsed)
    assert gate.run.failed == 0
    assert promote.run.succeeded > 0

    ready = await Repository(store, lane="ready").rows("questions")
    for row in ready:
        assert len(row["content_hash"]) == 64
        assert row["gate_status"] == "pass"


async def test_the_chain_refuses_what_cannot_be_answered(store: Store, config: Config) -> None:
    """A figure hint with no figure never reaches the work lane."""
    await seed_raw(store, [raw_row(text="The diagram above shows the arrangement.")])
    await run_task(Intake(), config, Repository(store, lane="work"), logical="questions")
    assert await Repository(store, lane="work").count("questions") == 0


# ---------------------------------------------------------------------------
# Promotion's conditions
# ---------------------------------------------------------------------------


def test_promotion_carries_section_explicitly() -> None:
    """Carrying it by omission is how the pipeline lost it."""
    ready = ready_row(raw_row(section="Section B"), "r_promote")
    assert ready["section"] == "Section B"


def test_promotion_drops_the_staging_bookkeeping() -> None:
    """The internal dedupe key goes. The provenance does not: see the next test."""
    ready = ready_row(
        raw_row(fingerprint="f", gate_reason="x", attempts=7, error="boom"),
        "r_promote",
    )
    assert "fingerprint" not in ready
    assert "gate_reason" not in ready
    # The bookkeeping columns are reset rather than removed, because the ready
    # table declares them and a row missing one would not insert.
    assert ready["attempts"] == 0
    assert ready["error"] is None


def test_promotion_keeps_what_the_api_reads() -> None:
    from utmelab_bank.model.question import QUESTION_COLUMNS

    ready = ready_row(raw_row(), "r_promote")
    missing = [c for c in QUESTION_COLUMNS if c not in ready]
    assert not missing, f"promotion drops columns the api reads: {missing}"


def test_promotion_keeps_where_the_content_came_from() -> None:
    """A ready row is still a question we fetched from somewhere."""
    ready = ready_row(raw_row(), "r_promote")
    assert ready["source_url"]
    assert ready["source_item_id"]
    assert ready["payload_hash"]


async def test_every_promoted_row_lands(store: Store, config: Config) -> None:
    """Promotion reported fifteen and wrote one, because every ready row carried
    the same empty provenance and collided on the raw lane's dedupe index.

    That index has no business on a lane where it is not a dedupe rule, so the
    test is here to catch the same collapse arriving by another route."""
    await seed_raw(store, [raw_row(id=f"q_{i}", payload_hash=f"{i:064d}") for i in range(12)])
    repo = Repository(store, lane="work")
    await run_task(Intake(), config, repo, logical="questions")
    result = await run_task(Promote(), config, repo, where="gated", logical="questions")

    assert result.run.succeeded == 12
    assert await Repository(store, lane="ready").count("questions") == 12


async def test_the_dedupe_index_is_raw_only(store: Store) -> None:
    """It is a property of scraping. On any other lane it collapses rows."""
    assert await store.table_exists("raw_questions")
    rows = await store.fetch_all("PRAGMA index_list('work_questions')")
    named = {str(row.get("name")) for row in rows}
    assert "idx_raw_q_source" not in named


def test_require_promotable_refuses_an_ungated_row() -> None:
    with pytest.raises(TaskError, match="has not passed the gate"):
        require_promotable({"id": "q1", "gate_status": "pending", "content_hash": "x"})


def test_require_promotable_refuses_an_unhashed_row() -> None:
    with pytest.raises(TaskError, match="no content hash"):
        require_promotable({"id": "q1", "gate_status": "pass", "content_hash": ""})


def test_work_row_clears_the_error_bookkeeping() -> None:
    """A fresh work row must not inherit a previous failure."""
    work = work_row(
        raw_row(error="boom", next_retry_at="2020-01-01T00:00:00+00:00"),
        judge_raw(raw_row()),
        "r_i",
    )
    assert work["error"] is None
    assert work["next_retry_at"] is None
    assert work["attempts"] == 0


async def test_intake_does_nothing_on_a_dry_run(store: Store, config: Config) -> None:
    await seed_raw(store, [raw_row()])
    dry = config.model_copy(update={"dry_run": False})
    result = await run_task(
        Intake(), dry, Repository(store, lane="work"), logical="questions", dry_run=True
    )
    assert await Repository(store, lane="work").count("questions") == 0
    assert result.run.succeeded == 1


async def test_ensure_schema_is_idempotent(store: Store) -> None:
    """A run brings the database to shape on the way in, every time."""
    await ensure_schema(store)
    await ensure_schema(store)
    assert await store.table_exists("work_questions")
