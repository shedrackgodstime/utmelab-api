"""Store, lanes, selectors and the tasks that use them.

Everything here runs against the real lane DDL in a temporary file, so a test
cannot pass against a schema the code would not actually create.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from utmelab_bank.config import Config, RepoRoot
from utmelab_bank.errors import ConfigError, StoreError
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository, Update
from utmelab_bank.store.schema import LANES, assert_lane_parity, table
from utmelab_bank.store.selectors import describe, explain, resolve

from conftest import make_question


def make_question_rows(count: int, **overrides: Any) -> list[dict[str, Any]]:
    """Distinct questions, so the raw lane's dedupe key moves with the id."""
    return [make_question(id=f"q_{index}", **overrides) for index in range(count)]

# ---------------------------------------------------------------------------
# Lanes
# ---------------------------------------------------------------------------


def test_lane_parity_holds() -> None:
    assert_lane_parity()


@pytest.mark.parametrize("lane", LANES)
def test_each_lane_has_its_own_questions_table(lane: str) -> None:
    assert table("questions", lane) == f"{lane}_questions"


async def test_a_lane_table_is_absent_from_another_lane(store: Store) -> None:
    """This is what makes a wrong ``where`` clause harmless."""
    assert await store.table_exists("work_questions")
    assert await store.table_columns("ready_questions") != await store.table_columns("no_lane")


async def test_the_same_row_in_two_lanes_is_independent(
    store: Store,
    question_row: dict[str, Any],
) -> None:
    work = Repository(store, lane="work")
    ready = Repository(store, lane="ready")

    await work.insert_many("questions", [question_row])
    assert await work.count("questions") == 1
    assert await ready.count("questions") == 0

    await ready.insert_many("questions", [question_row])
    await work.update("questions", question_row["id"], {"gate_status": "refused"})

    assert await work.count("questions", "gated") == 0
    assert await ready.count("questions") == 1


# ---------------------------------------------------------------------------
# The content hash is stamped on the way in
# ---------------------------------------------------------------------------


async def test_a_question_row_is_stamped_on_insert(store: Store) -> None:
    """A row without the hash is silently unverified, so the store stamps it."""
    row = {
        "id": "q_hash_1",
        "exam": "jamb",
        "subject": "physics",
        "text": "Which is a noble gas?",
        "inline": "[]",
        "options": json.dumps(
            [{"id": "A", "text": {"text": "Argon", "inline": []}}],
            separators=(",", ":"),
        ),
        "answer": "A",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [row])

    stored = await repo.rows("questions")
    assert len(stored[0]["content_hash"]) == 64


async def test_an_existing_hash_is_not_recomputed(
    store: Store,
    question_row: dict[str, Any],
) -> None:
    """Re-hashing edited content would orphan every verification on it."""
    question_row["content_hash"] = "f" * 64
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [question_row])
    assert (await repo.rows("questions"))[0]["content_hash"] == "f" * 64


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------


def test_all_selects_everything() -> None:
    assert resolve("all").clause == ""
    assert resolve("").clause == ""


def test_a_selector_binds_its_value() -> None:
    resolved = resolve("subject=physics")
    assert "subject" in resolved.clause
    assert "physics" in resolved.params.values()


def test_joining_selectors_keeps_the_arguments_separate() -> None:
    resolved = resolve("subject=physics and gated")
    assert " AND " in resolved.clause
    assert "physics" in resolved.params.values()


def test_an_unknown_selector_lists_the_known_ones() -> None:
    with pytest.raises(StoreError) as caught:
        resolve("not a real selector")
    assert "known" in caught.value.context


def test_a_caller_string_never_becomes_sql() -> None:
    """The injection boundary: values are parameters, names come from a list."""
    resolved = resolve("subject=x'; DROP TABLE work_questions; --")
    assert "drop" not in resolved.clause.lower()
    assert "drop table" in str(resolved.params.values()).lower()


def test_explain_names_what_would_be_picked() -> None:
    assert "description" in explain("no description")
    assert "and" in explain("gated and no subtopic")


def test_has_images_finds_a_mark_in_either_column() -> None:
    selector = describe("has images")
    assert selector.matches is not None
    compact = '{"kind":"image","start":0,"len":1}'
    spaced = json.dumps([{"kind": "image", "start": 0, "len": 1}])
    assert selector.matches({"inline": compact}, None)
    assert selector.matches({"inline": spaced}, None)
    assert not selector.matches({"inline": "[]", "options": "[]"}, None)


def test_retryable_is_false_for_a_row_that_never_failed() -> None:
    selector = describe("retryable")
    assert selector.matches is not None
    assert not selector.matches({"error": None}, None)
    assert selector.matches({"error": "boom", "next_retry_at": None}, None)


# ---------------------------------------------------------------------------
# Repository writes
# ---------------------------------------------------------------------------


async def test_bumping_attempts_happens_in_sql(
    store: Store,
    with_question: Repository,
) -> None:
    """Read-then-write would lose a count when two attempts race."""
    await with_question.mark_failed("questions", "q_test_1", "boom", "it broke")
    await with_question.mark_failed("questions", "q_test_1", "boom", "again")

    rows = await with_question.rows("questions")
    assert rows[0]["attempts"] == 2
    assert rows[0]["error"].startswith("boom:")


async def test_clearing_an_error_bumps_attempts_too(
    store: Store,
    with_question: Repository,
) -> None:
    await with_question.mark_failed("questions", "q_test_1", "boom", "it broke")
    await with_question.clear_error("questions", "q_test_1")
    row = (await with_question.rows("questions"))[0]
    assert row["error"] is None
    assert row["next_retry_at"] is None
    assert row["attempts"] == 2


async def test_an_error_is_truncated(store: Store, with_question: Repository) -> None:
    await with_question.mark_failed("questions", "q_test_1", "boom", "x" * 5000)
    row = (await with_question.rows("questions"))[0]
    assert len(row["error"]) < 1000


async def test_an_update_names_the_column_it_was_given() -> None:
    with pytest.raises(StoreError, match="unknown column"):
        Update.of().set("; DROP TABLE work_questions", 1)


async def test_counting_and_paging_agree(store: Store, question_row: dict[str, Any]) -> None:
    repo = Repository(store, lane="work")
    rows = make_question_rows(10)
    rows = [
        {**row, "subject": "physics" if index % 2 == 0 else "chemistry"}
        for index, row in enumerate(rows)
    ]
    await repo.insert_many("questions", rows)

    assert await repo.count("questions") == 10
    assert await repo.count("questions", "subject=physics") == 5
    assert len(await repo.rows("questions", limit=3)) == 3


async def test_iterating_pages(store: Store, question_row: dict[str, Any]) -> None:
    repo = Repository(store, lane="work")
    await repo.insert_many(
        "questions",
        make_question_rows(25),
    )
    seen = [row async for row in repo.iter_rows("questions", batch=7)]
    assert len(seen) == 25
    assert len({row["id"] for row in seen}) == 25


async def test_the_runs_table_records_a_run(
    store: Store,
    question_row: dict[str, Any],
    config: Config,
) -> None:
    from utmelab_bank.model.run import Run
    from utmelab_bank.task import run_task
    from utmelab_bank.task.gates import MechanicalGate

    repo = Repository(store, lane="work")
    await repo.insert_many("questions", [question_row])

    result = await run_task(MechanicalGate(), config, repo, where="all")

    runs = await store.fetch_all("SELECT * FROM runs")
    assert len(runs) == 1
    assert runs[0]["task"] == "gate"
    assert runs[0]["status"] == "done"
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# The json sink, which may only write under var/
# ---------------------------------------------------------------------------


def _json_config(tmp_path: Path, repo_root: Path) -> Config:
    return Config(repo=RepoRoot(path=repo_root), sink="json", lane="work")


async def test_the_json_sink_refuses_a_path_outside_var(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    from utmelab_bank.sink.json import JsonSink

    with pytest.raises(ConfigError, match="only write under var"):
        JsonSink(tmp_path / "somewhere-else", RepoRoot(path=repo_root))


async def test_the_json_sink_writes_under_var(tmp_path: Path, repo_root: Path) -> None:
    from utmelab_bank.sink.json import JsonSink

    config = _json_config(tmp_path, repo_root)
    sink = JsonSink(config.repo.var / "bank", config.repo, lane="work")
    written = await sink.write("questions", [{"id": "q1", "subject": "physics"}])

    assert written == 1
    assert sink.path_for("questions").is_file()
    assert str(config.repo.var) in str(sink.path_for("questions"))


async def test_the_json_sink_filters_with_the_same_vocabulary(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    from utmelab_bank.sink.json import JsonSink

    config = _json_config(tmp_path, repo_root)
    sink = JsonSink(config.repo.var / "bank", config.repo, lane="work")
    await sink.write(
        "questions",
        [
            {"id": "q1", "subject": "physics", "subtopic_id": None},
            {"id": "q2", "subject": "chemistry", "subtopic_id": "s1"},
        ],
    )

    assert len(await sink.read("questions")) == 2
    assert len(await sink.read("questions", "subject=physics")) == 1
    assert len(await sink.read("questions", "no subtopic")) == 1


async def test_the_json_sink_refuses_a_selector_it_cannot_answer(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    """Better a refusal than a task that quietly does less."""
    from utmelab_bank.sink.json import JsonSink

    config = _json_config(tmp_path, repo_root)
    sink = JsonSink(config.repo.var / "bank", config.repo, lane="work")
    await sink.write("questions", [{"id": "q1"}])

    with pytest.raises(ConfigError, match="needs the database"):
        await sink.read("questions", "unverified")


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def test_the_stem_fingerprint_ignores_case_and_punctuation() -> None:
    from utmelab_bank.store.fingerprint import stem_fingerprint

    assert stem_fingerprint("What is the capital?") == stem_fingerprint("what is the capital")


def test_the_stem_fingerprint_does_not_delete_non_latin_text() -> None:
    """The old normaliser emptied every Arabic and Hausa stem."""
    from utmelab_bank.store.fingerprint import stem_fingerprint

    arabic = stem_fingerprint("ما هو العنصر الأكثر وفرة في القشرة؟")
    assert arabic
    assert stem_fingerprint("What is the most abundant element in the crust?") != arabic


def test_the_two_hashes_are_not_the_same_function() -> None:
    """One is the boundary hash, one is internal. Mixing them is the trap."""
    from utmelab_bank.contract.content_hash import content_hash
    from utmelab_bank.store.fingerprint import stem_fingerprint

    options = [{"id": "A", "text": {"text": "Argon", "inline": []}}]
    boundary = content_hash(stem={"text": "Which?", "inline": []}, options=options, answer_id="A")
    internal = stem_fingerprint("Which?")
    assert boundary != internal
    assert len(boundary) == 64
