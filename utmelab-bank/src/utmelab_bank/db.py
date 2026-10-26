"""Read-only database access for operators and ad-hoc scripts.

The point of this module is that a token never leaves the environment. A
script imports it and asks a question:

    import asyncio
    from utmelab_bank.db import open_database

    async def main() -> None:
        async with open_database("bank") as db:
            result = await db.query(
                "SELECT state, COUNT(*) FROM staging_items GROUP BY state"
            )
            for state, count in result.rows:
                print(state, count)

    asyncio.run(main())

No URL, no token, no connection string. ``load_settings`` reads the same
``.env`` the pipeline uses, and every statement is checked before it runs.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from .adapters.database import DatabaseError, TursoClient, bank_client, prod_client
from .config import ConfigError, load_settings

#: Statements that only read. Anything else is refused.
READ_VERBS = frozenset({"select", "with", "pragma", "explain", "values"})

#: A write anywhere in a statement that claims to be a read is refused, so a
#: ``WITH ... DELETE`` cannot slip past the first-word check.
WRITE_VERBS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "replace",
        "create",
        "drop",
        "alter",
        "attach",
        "detach",
        "vacuum",
        "reindex",
        "begin",
        "commit",
        "rollback",
        "savepoint",
        "release",
    }
)

DATABASES = ("bank", "prod")


class ReadOnlyError(DatabaseError):
    """A statement that could change a database was refused."""


@dataclass(frozen=True)
class QueryResult:
    """The columns and rows one query returned."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]

    def as_dicts(self) -> list[dict[str, Any]]:
        """The rows keyed by column name, which is what ``--json`` prints."""
        return [dict(zip(self.columns, row, strict=False)) for row in self.rows]

    def __len__(self) -> int:
        return len(self.rows)


def _first_word(sql: str) -> str:
    """The first word of a statement, ignoring leading comments."""
    text = sql.lstrip()
    while text.startswith("--"):
        _, _, text = text.partition("\n")
        text = text.lstrip()
    head = text.split(None, 1)[0] if text else ""
    return head.rstrip(";").lower()


def check_read_only(sql: str) -> None:
    """Refuse anything that is not a plain read.

    Quoted text is removed first, so a value that happens to contain the word
    ``delete`` does not look like a write.
    """
    if not sql.strip():
        raise ReadOnlyError("an empty query is not a query")
    verb = _first_word(sql)
    if verb not in READ_VERBS:
        raise ReadOnlyError(f"read-only tool: {verb or 'statement'} is not a read")
    without_strings = re.sub(r"'(?:''|[^'])*'", "''", sql.lower())
    words = set(re.findall(r"[a-z_]+", without_strings))
    forbidden = sorted(words & WRITE_VERBS)
    if forbidden:
        raise ReadOnlyError(f"read-only tool: statement contains {', '.join(forbidden)}")


class Database:
    """One database, opened through the settings, queried read-only."""

    def __init__(self, client: TursoClient, *, name: str) -> None:
        if name not in DATABASES:
            raise ValueError(f"unknown database {name!r}; known databases: {', '.join(DATABASES)}")
        self.name = name
        self._client = client

    async def query(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> QueryResult:
        """Run one read-only statement and return its columns and rows."""
        check_read_only(sql)
        result = await self._client.execute(sql, list(params or ()))
        return QueryResult(columns=result.columns, rows=tuple(result.rows))

    async def close(self) -> None:
        await self._client.close()


@asynccontextmanager
async def open_database(name: str = "bank") -> AsyncIterator[Database]:
    """Open the bank or the production database for reading.

    The production client is built with the read-only token, so the database
    itself refuses a write even if this module ever let one through.
    """
    if name not in DATABASES:
        raise ConfigError(f"unknown database {name!r}; known databases: {', '.join(DATABASES)}")
    settings = load_settings()
    client = bank_client(settings) if name == "bank" else prod_client(settings)
    database = Database(client, name=name)
    try:
        yield database
    finally:
        await database.close()


__all__ = [
    "DATABASES",
    "Database",
    "QueryResult",
    "ReadOnlyError",
    "check_read_only",
    "open_database",
]
