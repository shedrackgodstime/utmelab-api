"""The fill plan table: seeding, ordering, and the status transitions.

The queries are small but the plan is the only memory a run has, so each
transition is checked against the real schema rather than a fake.
"""

from __future__ import annotations

from collections.abc import Sequence

from utmelab_bank.store import targets
from utmelab_bank.store.client import Store


async def seed_plan(
    store: Store,
    *,
    subjects: Sequence[tuple[str, int]] = (("physics", 0), ("chemistry", 1)),
    years: Sequence[int] = (2024, 2025),
) -> int:
    return await targets.seed(
        store,
        source="myschool",
        exam="jamb",
        subjects=subjects,
        years=years,
    )


async def test_seed_creates_every_target_once(store: Store) -> None:
    assert await seed_plan(store) == 4
    assert await seed_plan(store) == 0
    rows = await store.fetch_all("SELECT status FROM scrape_targets")
    assert len(rows) == 4
    assert {row["status"] for row in rows} == {"pending"}


async def test_an_empty_plan_has_no_next_target(store: Store) -> None:
    assert await targets.next_target(store, source="myschool", exam="jamb") is None


async def test_next_target_takes_the_newest_year_then_the_map_order(store: Store) -> None:
    await seed_plan(store)
    first = await targets.next_target(store, source="myschool", exam="jamb")
    assert first is not None
    assert (first["year"], first["subject"]) == (2025, "physics")

    await targets.mark_drained(store, first, rows_seen=1, rows_new=1, pages=1)
    second = await targets.next_target(store, source="myschool", exam="jamb")
    assert second is not None
    assert (second["year"], second["subject"]) == (2025, "chemistry")


async def test_excluded_subjects_are_skipped(store: Store) -> None:
    await seed_plan(store)
    found = await targets.next_target(
        store,
        source="myschool",
        exam="jamb",
        exclude_subjects={"physics"},
    )
    assert found is not None
    assert found["subject"] == "chemistry"


async def test_mark_active_counts_the_attempt(store: Store) -> None:
    await seed_plan(store, subjects=(("physics", 0),), years=(2025,))
    target = await targets.next_target(store, source="myschool", exam="jamb")
    assert target is not None
    await targets.mark_active(store, target, now="2026-01-01T00:00:00+00:00")
    stored = await store.fetch_one("SELECT * FROM scrape_targets")
    assert stored is not None
    assert stored["status"] == "active"
    assert stored["attempts"] == 1
    assert stored["started_at"] == "2026-01-01T00:00:00+00:00"


async def test_mark_drained_records_the_counts(store: Store) -> None:
    await seed_plan(store, subjects=(("physics", 0),), years=(2025,))
    target = await targets.next_target(store, source="myschool", exam="jamb")
    assert target is not None
    await targets.mark_drained(store, target, rows_seen=12, rows_new=3, pages=2)
    stored = await store.fetch_one("SELECT * FROM scrape_targets")
    assert stored is not None
    assert stored["status"] == "drained"
    assert (stored["rows_seen"], stored["rows_new"], stored["pages"]) == (12, 3, 2)
    assert stored["finished_at"] is not None


async def test_mark_empty_records_zero_rows(store: Store) -> None:
    await seed_plan(store, subjects=(("physics", 0),), years=(2025,))
    target = await targets.next_target(store, source="myschool", exam="jamb")
    assert target is not None
    await targets.mark_empty(store, target, pages=1)
    stored = await store.fetch_one("SELECT * FROM scrape_targets")
    assert stored is not None
    assert stored["status"] == "empty"
    assert stored["rows_seen"] == 0


async def test_a_failed_target_waits_for_its_backoff(store: Store) -> None:
    await seed_plan(store, subjects=(("physics", 0),), years=(2025,))
    target = await targets.next_target(store, source="myschool", exam="jamb")
    assert target is not None

    await targets.mark_failed(
        store,
        target,
        "TimeoutError: slow",
        now="2026-01-01T00:00:00+00:00",
    )
    stored = await store.fetch_one("SELECT * FROM scrape_targets")
    assert stored is not None
    assert stored["status"] == "failed"
    assert stored["last_error"] == "TimeoutError: slow"
    assert stored["next_retry_at"] == "2026-01-01T00:00:30+00:00"

    assert (
        await targets.next_target(
            store,
            source="myschool",
            exam="jamb",
            now="2026-01-01T00:00:10+00:00",
        )
        is None
    )
    found = await targets.next_target(
        store,
        source="myschool",
        exam="jamb",
        now="2026-01-01T00:00:31+00:00",
    )
    assert found is not None


async def test_a_long_error_is_truncated(store: Store) -> None:
    await seed_plan(store, subjects=(("physics", 0),), years=(2025,))
    target = await targets.next_target(store, source="myschool", exam="jamb")
    assert target is not None
    await targets.mark_failed(store, target, "x" * 900)
    stored = await store.fetch_one("SELECT last_error FROM scrape_targets")
    assert stored is not None
    assert len(stored["last_error"]) == 500


async def test_reset_requeues_only_the_selected_slice(store: Store) -> None:
    await seed_plan(store)
    rows = await store.fetch_all("SELECT * FROM scrape_targets WHERE year = 2025")
    for row in rows:
        await targets.mark_empty(store, row)

    assert await targets.reset(store, source="myschool", exam="jamb", years=(2025,)) == 2
    stored = await store.fetch_all("SELECT status FROM scrape_targets WHERE year = 2025")
    assert {row["status"] for row in stored} == {"pending"}


async def test_reset_can_be_limited_to_a_subject(store: Store) -> None:
    await seed_plan(store)
    rows = await store.fetch_all("SELECT * FROM scrape_targets")
    for row in rows:
        await targets.mark_empty(store, row)

    assert await targets.reset(store, source="myschool", exam="jamb", subjects=("physics",)) == 2
    physics = await store.fetch_all("SELECT status FROM scrape_targets WHERE subject = 'physics'")
    chemistry = await store.fetch_all(
        "SELECT status FROM scrape_targets WHERE subject = 'chemistry'"
    )
    assert {row["status"] for row in physics} == {"pending"}
    assert {row["status"] for row in chemistry} == {"empty"}


async def test_counts_groups_by_status(store: Store) -> None:
    await seed_plan(store)
    rows = await store.fetch_all("SELECT * FROM scrape_targets WHERE year = 2025")
    for row in rows:
        await targets.mark_empty(store, row)

    assert await targets.counts(store, source="myschool", exam="jamb") == {
        "empty": 2,
        "pending": 2,
    }


def test_target_id_is_stable() -> None:
    assert targets.target_id("myschool", "jamb", "physics", 2025) == "myschool|jamb|physics|2025"
