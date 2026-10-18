"""Every read and write against the bank database.

One module owns every statement, which is the claim the pipeline could not make:
its CLI, its promoter, its sync step and its metrics collector all built SQL
themselves and four of the five consumers bypassed its own repository.

Two disciplines hold here.

**Batched writes.** A task that touches 200 rows issues one batch, not 200 round
trips. Every write also goes through :meth:`Repository.update`, which sets
``updated_at`` and bumps ``attempts``, so no task has to remember to.

**No interpolation.** Parameters are bound. The only interpolated identifiers
are table names from :mod:`utmelab_bank.store.schema` and column names from the
model layer, never anything a caller typed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from typing import TYPE_CHECKING, Any

from utmelab_bank.config import Lane
from utmelab_bank.contract.content_hash import stamp_rows
from utmelab_bank.errors import StoreError
from utmelab_bank.model.base import now_iso
from utmelab_bank.model.run import Run
from utmelab_bank.store import selectors
from utmelab_bank.store.schema import table

if TYPE_CHECKING:
    from utmelab_bank.store.client import Store

__all__ = ["Repository", "Update"]


class Update(dict[str, Any]):
    """A partial row update. Keys must be real columns.

    Constructed through :meth:`of` so the key check happens in one place rather
    than being forgotten by a caller.
    """

    @classmethod
    def of(cls, **values: Any) -> Update:
        update = cls()
        for key, value in values.items():
            update.set(key, value)
        return update

    def set(self, key: str, value: Any) -> None:
        if not selectors.is_known_column(key) and key not in _EXTRA_COLUMNS:
            raise StoreError("unknown column in update", column=key)
        self[key] = value


_EXTRA_COLUMNS: frozenset[str] = frozenset(
    {"source_url", "source_item_id", "payload_hash", "kind", "status"}
)

#: Catalog tables are keyed by ``slug``, not ``id``. Everything else carries
#: ``created_at`` and ``id``, so it orders by both.
_ORDER: frozenset[str] = frozenset({"subjects", "topics", "subtopics"})


def _order_for(physical: str) -> str:
    """The ORDER BY for one physical table, as a fragment including the space."""
    for logical in _ORDER:
        if physical.endswith(logical):
            return f' ORDER BY "{physical}"."created_at", "{physical}"."slug"'
    return f' ORDER BY "{physical}"."created_at", "{physical}"."id"'


class Repository:
    """Lane-aware reads and writes. Constructed once per run."""

    def __init__(self, store: Store, lane: Lane = "work") -> None:
        self._store = store
        self._lane = lane

    @property
    def lane(self) -> Lane:
        return self._lane

    def in_lane(self, lane: Lane) -> Repository:
        """The same store pointed at another lane.

        Promotion is the only caller, and it reads one lane while writing
        another, so this exists to make that explicit at the call site.
        """
        return Repository(self._store, lane)

    def name(self, logical: str) -> str:
        return table(logical, self._lane)

    # -- reads ------------------------------------------------------------

    async def rows(
        self,
        logical: str,
        where: str = "all",
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        """Rows matching a selector expression.

        Bounded by default in the sense that an unbounded read is a deliberate
        choice: the caller passes ``limit=None`` and says so.
        """
        physical = self.name(logical)
        resolved = selectors.resolve(where, table=physical)
        sql = f'SELECT * FROM "{physical}"'
        if resolved.clause:
            sql += f" WHERE {resolved.clause}"
        sql += _order_for(physical)
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
            if offset:
                sql += f" OFFSET {int(offset)}"
        return await self._store.fetch_all(sql, resolved.params)

    async def count(self, logical: str, where: str = "all") -> int:
        physical = self.name(logical)
        resolved = selectors.resolve(where, table=physical)
        sql = f'SELECT COUNT(*) AS n FROM "{physical}"'
        if resolved.clause:
            sql += f" WHERE {resolved.clause}"
        value = await self._store.scalar(sql, resolved.params)
        return int(value or 0)

    async def iter_rows(
        self,
        logical: str,
        where: str = "all",
        *,
        batch: int = 200,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream rows in batches, so a 50 000 row run is not held in memory."""
        offset = 0
        while True:
            chunk = await self.rows(logical, where, limit=batch, offset=offset)
            if not chunk:
                return
            for row in chunk:
                yield row
            if len(chunk) < batch:
                return
            offset += batch

    # -- writes -----------------------------------------------------------

    async def insert(
        self,
        logical: str,
        row: dict[str, Any],
        *,
        ignore_conflict: bool = True,
    ) -> None:
        """Insert one row."""
        physical = self.name(logical)
        verb = "INSERT OR IGNORE" if ignore_conflict else "INSERT"
        columns = ", ".join(f'"{key}"' for key in row)
        markers = ", ".join(f":{key}" for key in row)
        await self._store.execute(
            f'{verb} INTO "{physical}" ({columns}) VALUES ({markers})',
            row,
        )

    async def insert_many(self, logical: str, rows: Sequence[dict[str, Any]]) -> int:
        """Insert a batch in one round trip. Returns how many were written.

        Question rows get their content hash stamped here rather than by the
        caller, because that hash is the field the API joins on and a row
        missing it is silently unverified. One stamping point means no task can
        forget it and no task can do it differently.
        """
        if not rows:
            return 0
        if logical == "questions":
            rows = stamp_rows([dict(row) for row in rows])
        physical = self.name(logical)
        keys = list(rows[0])
        columns = ", ".join(f'"{key}"' for key in keys)
        markers = ", ".join(f":{key}" for key in keys)
        statements = [
            (f'INSERT OR IGNORE INTO "{physical}" ({columns}) VALUES ({markers})', dict(row))
            for row in rows
        ]
        return await self._store.execute_many(statements)

    async def update(
        self,
        logical: str,
        row_id: str,
        update: Update | dict[str, Any],
        *,
        bump_attempts: bool = False,
    ) -> None:
        """Patch one row. Always stamps ``updated_at``."""
        physical = self.name(logical)
        values = dict(update)
        if not values and not bump_attempts:
            return
        values["updated_at"] = now_iso()
        await self._flush_one(physical, row_id, values, bump_attempts=bump_attempts)

    async def _flush_one(
        self,
        physical: str,
        row_id: str,
        values: dict[str, Any],
        *,
        bump_attempts: bool = False,
    ) -> None:
        assignments = [f'"{key}" = :{key}' for key in values]
        if bump_attempts:
            # Incremented in sql rather than read-then-written, so two
            # concurrent attempts on one row cannot lose an attempt count.
            assignments.append('"attempts" = COALESCE("attempts", 0) + 1')
        await self._store.execute(
            f'UPDATE "{physical}" SET {", ".join(assignments)} WHERE "id" = :__row_id',
            {**values, "__row_id": row_id},
        )

    async def update_many(
        self,
        logical: str,
        updates: Iterable[tuple[str, Update | dict[str, Any]]],
        *,
        batch: int = 200,
    ) -> int:
        """Patch many rows in batches. Returns how many rows changed."""
        physical = self.name(logical)
        written = 0
        chunk: list[tuple[str, dict[str, Any]]] = []
        for row_id, update in updates:
            values = dict(update)
            values["updated_at"] = now_iso()
            chunk.append((row_id, values))
            if len(chunk) >= batch:
                written += await self._flush(physical, chunk)
                chunk = []
        if chunk:
            written += await self._flush(physical, chunk)
        return written

    async def _flush(self, physical: str, chunk: list[tuple[str, dict[str, Any]]]) -> int:
        statements = []
        for row_id, values in chunk:
            assignments = ", ".join(f'"{key}" = :{key}' for key in values)
            statements.append(
                (
                    f'UPDATE "{physical}" SET {assignments} WHERE "id" = :__row_id',
                    {**values, "__row_id": row_id},
                )
            )
        await self._store.execute_many(statements)
        return len(statements)

    async def mark_failed(
        self,
        logical: str,
        row_id: str,
        code: str,
        detail: str,
        *,
        retry_at: str | None = None,
    ) -> None:
        """Record a failure on a row and schedule the next attempt.

        The error text is truncated because a model that returned a whole page
        of prose would otherwise land in a row somebody has to read later.
        """
        await self._flush_one(
            self.name(logical),
            row_id,
            {"error": f"{code}: {detail}"[:900], "next_retry_at": retry_at},
            bump_attempts=True,
        )

    async def clear_error(self, logical: str, row_id: str) -> None:
        await self._flush_one(
            self.name(logical),
            row_id,
            {"error": None, "next_retry_at": None},
            bump_attempts=True,
        )

    # -- runs -------------------------------------------------------------

    async def open_run(self, run: Run) -> None:
        await self._store.execute(
            "INSERT INTO runs (id, task, target, selector, sink, status, started_at) "
            "VALUES (:id, :task, :target, :selector, :sink, :status, :started_at) "
            "ON CONFLICT(id) DO NOTHING",
            {
                "id": run.id,
                "task": run.task,
                "target": run.target,
                "selector": run.selector,
                "sink": run.sink,
                "status": run.status,
                "started_at": run.started_at,
            },
        )

    async def close_run(self, run: Run) -> None:
        await self._store.execute(
            "UPDATE runs SET status = :status, total = :total, succeeded = :succeeded, "
            "skipped = :skipped, failed = :failed, finished_at = :finished_at, "
            "detail = :detail WHERE id = :id",
            {
                "id": run.id,
                "status": run.status,
                "total": run.total,
                "succeeded": run.succeeded,
                "skipped": run.skipped,
                "failed": run.failed,
                "finished_at": run.finished_at,
                "detail": run.detail,
            },
        )

    async def record_outcomes(
        self, run_id: str, outcomes: Sequence[tuple[str, str, str | None]]
    ) -> None:
        """Persist ``(row_id, state, code)`` triples for a finished run."""
        if not outcomes:
            return
        statements = [
            (
                "INSERT INTO run_outcomes (run_id, row_id, state, code, retryable, created_at) "
                "VALUES (:run_id, :row_id, :state, :code, :retryable, :created_at) "
                "ON CONFLICT(run_id, row_id) DO UPDATE SET state = excluded.state",
                {
                    "run_id": run_id,
                    "row_id": row_id,
                    "state": state,
                    "code": code,
                    "retryable": 0,
                    "created_at": now_iso(),
                },
            )
            for row_id, state, code in outcomes
        ]
        await self._store.execute_many(statements)
