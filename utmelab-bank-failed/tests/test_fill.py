"""The fill loop: the slice it plans, and what it records after a fetch.

The loop is driven with a fake fetcher, so the tests prove the planner and the
state transitions without touching the network. The real fetcher is one thin
adapter over :func:`fetch_subject` and is covered by the source's own tests.
"""

from __future__ import annotations

from typing import Any

import pytest

from utmelab_bank.config import Config
from utmelab_bank.errors import ConfigError, SourceError
from utmelab_bank.fill import Batch, FillOptions, _scope, plan, run_fill
from utmelab_bank.source.base import FetchRequest
from utmelab_bank.source.myschool.parser import parse_api_question
from utmelab_bank.source.myschool.subjects import subjects_for
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository

# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def options(**overrides: Any) -> FillOptions:
    base: dict[str, Any] = {
        "exam": "jamb",
        "subjects": ("physics",),
        "from_year": 2025,
        "to_year": 2025,
        "minutes": 1.0,
    }
    base.update(overrides)
    return FillOptions(**base)


def test_the_default_window_is_the_default_year_back_ten_years() -> None:
    _, subjects, years = _scope(FillOptions(exam="jamb", subjects=("physics",)))
    mapped = subjects_for("jamb")
    assert years[0] == mapped.default_year
    assert years[-1] == mapped.default_year - 10
    assert len(years) == 11
    assert [entry.slug for entry, _ in subjects] == ["physics"]


def test_plan_is_year_major_then_map_order() -> None:
    opts = FillOptions(exam="jamb", subjects=("physics", "chemistry"), from_year=2024, to_year=2025)
    _, subjects, _ = _scope(opts)
    rows = plan(opts)
    assert [row["year"] for row in rows] == [2025, 2025, 2024, 2024]
    assert [row["subject"] for row in rows[:2]] == [entry.slug for entry, _ in subjects]


def test_a_subject_can_be_named_by_its_source_slug() -> None:
    mapped = subjects_for("jamb")
    entry = next(item for item in mapped.subjects if item.source != item.slug)
    _, by_source, _ = _scope(FillOptions(exam="jamb", subjects=(entry.source,)))
    _, by_slug, _ = _scope(FillOptions(exam="jamb", subjects=(entry.slug,)))
    assert by_source[0][0].slug == entry.slug
    assert by_slug[0][0].slug == entry.slug


def test_an_unknown_subject_is_refused() -> None:
    with pytest.raises(SourceError):
        _scope(FillOptions(exam="jamb", subjects=("not-a-subject",)))


def test_an_unknown_exam_is_refused() -> None:
    with pytest.raises(SourceError):
        _scope(FillOptions(exam="not-an-exam"))


def test_a_backwards_window_is_refused() -> None:
    with pytest.raises(ConfigError):
        _scope(FillOptions(exam="jamb", from_year=2025, to_year=2024))


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def api_row(index: int = 74347) -> dict[str, Any]:
    return {
        "id": index,
        "question": f"<p>Which of these colours has the longest wavelength? {index}</p>",
        "options": [
            {"id": 1, "tag": "a", "description": "Red", "is_correct": 1},
            {"id": 2, "tag": "b", "description": "Blue", "is_correct": 0},
            {"id": 3, "tag": "c", "description": "Green", "is_correct": 0},
        ],
        "image": None,
        "collection": {"id": 1273, "exam_year": 2025, "exam_type": "jamb"},
    }


def parsed(index: int = 74347) -> Any:
    return parse_api_question(api_row(index), exam="jamb", subject="physics", year=2025)


class FakeFetch:
    """One scripted answer per ``(subject, year)``, and a record of the asks."""

    def __init__(self, results: dict[tuple[str, int], Batch | Exception]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, request: FetchRequest) -> Batch:
        key = (request.subject, request.year or 0)
        self.calls.append(key)
        result = self.results[key]
        if isinstance(result, Exception):
            raise result
        return result


async def test_a_target_is_fetched_and_marked_drained(store: Store, config: Config) -> None:
    fetch = FakeFetch({("physics", 2025): Batch([parsed(1), parsed(2)], pages=1)})
    report = await run_fill(config, store, options(), fetch=fetch)

    assert report.seeded == 1
    assert report.attempted == 1
    assert report.drained == 1
    assert report.rows_seen == 2
    assert report.rows_new == 2
    assert report.reason == "done"

    raw = Repository(store, lane="raw")
    assert await raw.count("questions") == 2
    stored = await store.fetch_one("SELECT status, pages FROM scrape_targets")
    assert stored is not None
    assert stored["status"] == "drained"
    assert stored["pages"] == 1


async def test_a_drained_target_is_not_fetched_again(store: Store, config: Config) -> None:
    fetch = FakeFetch({("physics", 2025): Batch([parsed(1)])})
    await run_fill(config, store, options(), fetch=fetch)

    second = await run_fill(config, store, options(), fetch=fetch)
    assert second.attempted == 0
    assert second.seeded == 0
    assert second.reason == "done"
    assert len(fetch.calls) == 1


async def test_refresh_rechecks_without_adding_rows(store: Store, config: Config) -> None:
    fetch = FakeFetch({("physics", 2025): Batch([parsed(1)])})
    await run_fill(config, store, options(), fetch=fetch)

    second = await run_fill(config, store, options(refresh=True), fetch=fetch)
    assert second.reset == 1
    assert second.attempted == 1
    assert second.rows_seen == 1
    assert second.rows_new == 0
    assert len(fetch.calls) == 2


async def test_an_empty_target_is_marked_empty(store: Store, config: Config) -> None:
    fetch = FakeFetch({("physics", 2025): Batch([], pages=1)})
    report = await run_fill(config, store, options(), fetch=fetch)

    assert report.empty == 1
    assert report.rows_new == 0
    stored = await store.fetch_one("SELECT status FROM scrape_targets")
    assert stored is not None
    assert stored["status"] == "empty"


async def test_a_failed_target_is_marked_failed(store: Store, config: Config) -> None:
    fetch = FakeFetch({("physics", 2025): TimeoutError("slow")})
    report = await run_fill(config, store, options(), fetch=fetch)

    assert report.failed == 1
    stored = await store.fetch_one("SELECT status, last_error, next_retry_at FROM scrape_targets")
    assert stored is not None
    assert stored["status"] == "failed"
    assert "TimeoutError" in stored["last_error"]
    assert stored["next_retry_at"]


async def test_max_targets_stops_the_run(store: Store, config: Config) -> None:
    fetch = FakeFetch(
        {
            ("physics", 2025): Batch([parsed(1)]),
            ("physics", 2024): Batch([parsed(2)]),
        }
    )
    report = await run_fill(
        config,
        store,
        options(from_year=2024, max_targets=1),
        fetch=fetch,
    )

    assert report.attempted == 1
    assert report.reason == "limit"
    rows = await store.fetch_all("SELECT status FROM scrape_targets ORDER BY year DESC")
    assert [row["status"] for row in rows] == ["drained", "pending"]


async def test_a_dry_subject_is_set_aside_for_the_run(store: Store, config: Config) -> None:
    fetch = FakeFetch(
        {
            ("physics", 2025): Batch([]),
            ("physics", 2024): Batch([]),
            ("physics", 2023): Batch([]),
            ("physics", 2022): Batch([parsed(1)]),
        }
    )
    report = await run_fill(
        config,
        store,
        options(from_year=2022, to_year=2025),
        fetch=fetch,
    )

    assert report.empty == 3
    assert report.attempted == 3
    assert fetch.calls == [("physics", 2025), ("physics", 2024), ("physics", 2023)]


async def test_a_non_myschool_source_is_refused(store: Store, config: Config) -> None:
    with pytest.raises(SourceError):
        await run_fill(config, store, options(source="elsewhere"), fetch=FakeFetch({}))


async def test_a_non_positive_budget_is_refused(store: Store, config: Config) -> None:
    with pytest.raises(ConfigError):
        await run_fill(config, store, options(minutes=0), fetch=FakeFetch({}))
