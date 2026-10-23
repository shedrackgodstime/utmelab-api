"""Probe the live database against what the API says it reads.

This is the writer's half of the shape check. The API runs its own version on
every boot and on every re-check, and fails closed. We run this before we write,
so a shape the API would reject is discovered here rather than after a thousand
rows have been written against it.

It also catches what the API cannot see. ``READ_SHAPES`` asserts that columns
exist, not that anything is written into them, which is how ``section`` became
permanently null on every pipeline-synced question while the contract stayed
green. :func:`check_shapes` with ``deep=True`` is the check for that.

Every statement is spelled in :mod:`utmelab_bank.store.client`, so the rule that
all sql lives in ``store`` stays true. This module asks questions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from utmelab_bank.contract.rust_schema import ReadShape, RustContract
from utmelab_bank.errors import ContractError

if TYPE_CHECKING:
    from utmelab_bank.store.client import Store

__all__ = [
    "ShapeReport",
    "check_shapes",
    "read_contract_version",
    "require_ready",
]

CONTRACT_KEY: str = "contract_version"


@dataclass(frozen=True)
class ShapeReport:
    """What the probe found. Every list is a problem, so an empty report passes."""

    missing_tables: tuple[str, ...] = ()
    missing_columns: tuple[str, ...] = ()
    never_written: tuple[str, ...] = ()
    checked_tables: int = 0

    @property
    def ok(self) -> bool:
        return not (self.missing_tables or self.missing_columns or self.never_written)

    def reason(self) -> str | None:
        """One sentence naming the first problem, or ``None`` when clean."""
        if self.missing_tables:
            return f"table missing: {self.missing_tables[0]}"
        if self.missing_columns:
            return f"column missing: {self.missing_columns[0]}"
        if self.never_written:
            return (
                f"column present but never written: {self.never_written[0]}, "
                "so the contract passes while the data is empty"
            )
        return None

    def summary(self) -> str:
        if self.ok:
            return f"{self.checked_tables} tables match the shapes the api declares"
        parts: list[str] = []
        if self.missing_tables:
            parts.append(f"{len(self.missing_tables)} tables missing")
        if self.missing_columns:
            parts.append(f"{len(self.missing_columns)} columns missing")
        if self.never_written:
            parts.append(f"{len(self.never_written)} columns never written")
        return "; ".join(parts)


async def check_shapes(
    store: Store,
    contract: RustContract,
    *,
    shapes: tuple[ReadShape, ...] | None = None,
    deep: bool = False,
) -> ShapeReport:
    """Compare the live tables against ``READ_SHAPES``.

    ``deep`` additionally counts rows and names the columns that are present but
    hold nothing. That costs a full scan per column, so it is opt in, and it is
    the only check that would have caught the null ``section`` column.
    """
    targets = shapes if shapes is not None else contract.read_shapes
    missing_tables: list[str] = []
    missing_columns: list[str] = []
    never_written: list[str] = []

    for shape in targets:
        present = await store.table_columns(shape.table)
        if not present:
            missing_tables.append(shape.table)
            continue
        missing_columns.extend(f"{shape.table}.{column}" for column in shape.missing_from(present))

    if deep and not missing_tables:
        never_written = await _never_written(store, targets)

    return ShapeReport(
        missing_tables=tuple(missing_tables),
        missing_columns=tuple(missing_columns),
        never_written=tuple(never_written),
        checked_tables=len(targets),
    )


async def _never_written(store: Store, targets: tuple[ReadShape, ...]) -> list[str]:
    """Columns that exist, in a table with rows, and hold nothing anywhere."""
    empty: list[str] = []
    for shape in targets:
        if not shape.columns:
            continue
        if await store.count_rows(shape.table) == 0:
            continue
        for column in shape.columns:
            filled = await store.count_where(shape.table, column, empty=False)
            if filled == 0:
                empty.append(f"{shape.table}.{column}")
    return empty


async def read_contract_version(store: Store) -> int | None:
    """The version the API stamped in ``meta``, or ``None``.

    Read only. ``meta`` is the API's table and the API stamps its own version on
    first boot, so the writer half of that handshake is not ours to perform. We
    read what it said and refuse to write when we do not understand it, which is
    the opposite direction and needs nothing from the other side.
    """
    raw = await store.get_meta(CONTRACT_KEY)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


async def require_ready(store: Store, contract: RustContract, *, action: str = "write") -> None:
    """The gate every write passes: a known version, and the shapes present.

    Raises :class:`ContractError` naming the first problem. A caller that wants
    a report instead of a raise uses :func:`check_shapes` directly.
    """
    from utmelab_bank.contract.version import refuse_unknown

    refuse_unknown(await read_contract_version(store), contract, action=action)
    report = await check_shapes(store, contract)
    reason = report.reason()
    if reason is not None:
        raise ContractError(
            reason,
            action=action,
            summary=report.summary(),
            hint="run `utmelab-bank contract --deep` for the full report",
        )
