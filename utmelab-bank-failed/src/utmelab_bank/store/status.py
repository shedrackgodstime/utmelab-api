"""Read-only counts for the status report.

The SQL lives here, next to the repository, because the architecture rule is
that a module outside ``store`` never writes a statement. The report module
formats what these functions return and asks selectors for the rest.
"""

from __future__ import annotations

from typing import Any

from utmelab_bank.store.client import Store
from utmelab_bank.store.schema import LANE_TABLES, LANES, table

__all__ = ["grouped_counts", "lane_counts", "recent_runs"]


async def lane_counts(store: Store) -> dict[str, dict[str, int]]:
    """Every logical table, counted in every lane."""
    counts: dict[str, dict[str, int]] = {}
    for lane in LANES:
        counts[lane] = {}
        for logical in LANE_TABLES:
            physical = table(logical, lane)
            counts[lane][logical] = int(
                await store.scalar(f'SELECT COUNT(*) AS n FROM "{physical}"') or 0
            )
    return counts


async def grouped_counts(
    store: Store, physical: str, column: str, *, empty: str = "(none)"
) -> dict[str, int]:
    """Count one column's values, keeping the empty value visible."""
    rows = await store.fetch_all(
        f'SELECT COALESCE("{column}", :empty) AS key, COUNT(*) AS n '
        f'FROM "{physical}" GROUP BY 1 ORDER BY n DESC, key',
        {"empty": empty},
    )
    return {str(row["key"]): int(row["n"]) for row in rows}


async def recent_runs(store: Store, limit: int = 8) -> list[dict[str, Any]]:
    """The most recent runs, newest first."""
    return await store.fetch_all(
        "SELECT task, target, status, total, succeeded, skipped, failed, "
        "started_at, finished_at FROM runs ORDER BY started_at DESC LIMIT :limit",
        {"limit": limit},
    )
