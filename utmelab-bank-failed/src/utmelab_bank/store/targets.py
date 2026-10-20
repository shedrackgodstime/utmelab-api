"""The fill plan: seed the targets, pick the next one, record what happened.

The plan lives in the database because a runner is disposable. A GitHub job
that dies at the budget does not take the plan with it, and the next run reads
the same table and continues.

The table is global, not lane-specific. Acquisition is not a property of a
question; it is a property of the source and the slice of it we have walked.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any

from utmelab_bank.model.base import now_iso, parse_iso
from utmelab_bank.store.client import Store

__all__ = [
    "ACTIVE",
    "BACKOFF",
    "DRAINED",
    "EMPTY",
    "FAILED",
    "PENDING",
    "counts",
    "mark_active",
    "mark_drained",
    "mark_empty",
    "mark_failed",
    "next_target",
    "reset",
    "seed",
    "target_id",
]

PENDING = "pending"
ACTIVE = "active"
DRAINED = "drained"
EMPTY = "empty"
FAILED = "failed"

#: Seconds to wait before the next attempt, per attempt number. Capped so a
#: target that keeps timing out does not sit in the queue for a day.
BACKOFF: tuple[int, ...] = (30, 300, 1800, 7200)


def target_id(source: str, exam: str, subject: str, year: int) -> str:
    """A stable key, so seeding the same slice twice writes nothing."""
    return f"{source}|{exam}|{subject}|{year}"


def _placeholders(prefix: str, values: Sequence[Any]) -> tuple[str, dict[str, Any]]:
    names = [f":{prefix}{index}" for index in range(len(values))]
    return ", ".join(names), {f"{prefix}{index}": value for index, value in enumerate(values)}


async def seed(
    store: Store,
    *,
    source: str,
    exam: str,
    subjects: Sequence[tuple[str, int]],
    years: Sequence[int],
) -> int:
    """Create every target in the slice. Returns how many were new.

    ``INSERT OR IGNORE`` is the idempotence: a subject added to the map later
    is picked up on the next seed, and an existing target keeps its status.
    """
    stamp = now_iso()
    statements: list[tuple[str, dict[str, Any]]] = []
    for subject, order in subjects:
        for year in years:
            statements.append(
                (
                    """
                    INSERT OR IGNORE INTO scrape_targets
                        (id, source, exam, subject, subject_order, year, status,
                         created_at, updated_at)
                    VALUES
                        (:id, :source, :exam, :subject, :subject_order, :year,
                         :status, :created_at, :updated_at)
                    """,
                    {
                        "id": target_id(source, exam, subject, year),
                        "source": source,
                        "exam": exam,
                        "subject": subject,
                        "subject_order": order,
                        "year": year,
                        "status": PENDING,
                        "created_at": stamp,
                        "updated_at": stamp,
                    },
                )
            )
    return await store.execute_many(statements)


async def reset(
    store: Store,
    *,
    source: str,
    exam: str,
    subjects: Sequence[str] | None = None,
    years: Sequence[int] | None = None,
) -> int:
    """Put terminal targets back in the queue.

    ``--refresh`` is how a drained or empty slice is re-checked later, when the
    source may have published more. Returns how many targets moved.
    """
    where = [
        "source = :source",
        "exam = :exam",
        "status IN (:drained, :empty)",
    ]
    params: dict[str, Any] = {
        "source": source,
        "exam": exam,
        "drained": DRAINED,
        "empty": EMPTY,
        "pending": PENDING,
        "now": now_iso(),
    }
    if subjects:
        clause, extra = _placeholders("s", list(subjects))
        where.append(f"subject IN ({clause})")
        params.update(extra)
    if years:
        clause, extra = _placeholders("y", list(years))
        where.append(f"year IN ({clause})")
        params.update(extra)
    sql = (
        "UPDATE scrape_targets SET status = :pending, next_retry_at = NULL, "
        "updated_at = :now WHERE " + " AND ".join(where)
    )
    return await store.execute_many([(sql, params)])


async def next_target(
    store: Store,
    *,
    source: str,
    exam: str,
    exclude_subjects: Iterable[str] = (),
    now: str | None = None,
) -> dict[str, Any] | None:
    """The next target to fetch, newest year first.

    ``pending`` and ``active`` are always eligible. ``failed`` is eligible once
    its backoff has passed, which is what makes a network error a pause rather
    than a loss. ``exclude_subjects`` is the run-local dry-streak guard: a
    subject that keeps coming back empty is set aside without being written
    off for good.
    """
    stamp = now or now_iso()
    where = [
        "source = :source",
        "exam = :exam",
        (
            "(status = :pending OR status = :active OR "
            "(status = :failed AND (next_retry_at IS NULL OR next_retry_at <= :now)))"
        ),
    ]
    params: dict[str, Any] = {
        "source": source,
        "exam": exam,
        "pending": PENDING,
        "active": ACTIVE,
        "failed": FAILED,
        "now": stamp,
    }
    excluded = sorted(set(exclude_subjects))
    if excluded:
        clause, extra = _placeholders("x", excluded)
        where.append(f"subject NOT IN ({clause})")
        params.update(extra)
    sql = (
        "SELECT * FROM scrape_targets WHERE "
        + " AND ".join(where)
        + " ORDER BY year DESC, subject_order ASC LIMIT 1"
    )
    return await store.fetch_one(sql, params)


async def mark_active(store: Store, target: dict[str, Any], *, now: str | None = None) -> None:
    """Claim a target for this run, and count the attempt."""
    stamp = now or now_iso()
    await store.execute(
        "UPDATE scrape_targets SET status = :status, attempts = attempts + 1, "
        "started_at = COALESCE(started_at, :now), finished_at = NULL, "
        "last_error = NULL, next_retry_at = NULL, updated_at = :now "
        "WHERE id = :id",
        {"status": ACTIVE, "now": stamp, "id": target["id"]},
    )


async def mark_drained(
    store: Store,
    target: dict[str, Any],
    *,
    rows_seen: int,
    rows_new: int,
    pages: int,
    now: str | None = None,
) -> None:
    """The target was walked to its last page."""
    stamp = now or now_iso()
    await store.execute(
        "UPDATE scrape_targets SET status = :status, rows_seen = :rows_seen, "
        "rows_new = :rows_new, pages = :pages, finished_at = :now, "
        "last_error = NULL, next_retry_at = NULL, updated_at = :now "
        "WHERE id = :id",
        {
            "status": DRAINED,
            "rows_seen": rows_seen,
            "rows_new": rows_new,
            "pages": pages,
            "now": stamp,
            "id": target["id"],
        },
    )


async def mark_empty(
    store: Store,
    target: dict[str, Any],
    *,
    pages: int = 0,
    now: str | None = None,
) -> None:
    """The first page had nothing, so this slice has no paper."""
    stamp = now or now_iso()
    await store.execute(
        "UPDATE scrape_targets SET status = :status, rows_seen = 0, rows_new = 0, "
        "pages = :pages, finished_at = :now, last_error = NULL, "
        "next_retry_at = NULL, updated_at = :now WHERE id = :id",
        {"status": EMPTY, "pages": pages, "now": stamp, "id": target["id"]},
    )


async def mark_failed(
    store: Store,
    target: dict[str, Any],
    error: str,
    *,
    now: str | None = None,
) -> None:
    """Back the target off, keeping the reason for the next person."""
    stamp = now or now_iso()
    attempt = int(target.get("attempts") or 0) + 1
    delay = BACKOFF[min(max(attempt - 1, 0), len(BACKOFF) - 1)]
    retry_at = (parse_iso(stamp) + timedelta(seconds=delay)).replace(microsecond=0).isoformat()
    await store.execute(
        "UPDATE scrape_targets SET status = :status, attempts = attempts + 1, "
        "last_error = :error, next_retry_at = :retry_at, finished_at = :now, "
        "updated_at = :now WHERE id = :id",
        {
            "status": FAILED,
            "error": error[:500],
            "retry_at": retry_at,
            "now": stamp,
            "id": target["id"],
        },
    )


async def counts(store: Store, *, source: str, exam: str) -> dict[str, int]:
    """How the plan stands, by status."""
    rows = await store.fetch_all(
        "SELECT status, COUNT(*) AS n FROM scrape_targets "
        "WHERE source = :source AND exam = :exam GROUP BY status",
        {"source": source, "exam": exam},
    )
    return {str(row["status"]): int(row["n"]) for row in rows}
