"""The read-only database surface and its separate CLI."""

from __future__ import annotations

from typing import Any

import pytest

from utmelab_bank.adapters.database import Result
from utmelab_bank.config import ConfigError
from utmelab_bank.db import (
    Database,
    QueryResult,
    ReadOnlyError,
    check_read_only,
)
from utmelab_bank.db_cli import MAX_ROWS, _limit, build_parser, format_table


class FakeClient:
    """A client that records the statement and answers with fixed rows."""

    def __init__(self, rows: list[tuple[Any, ...]], columns: tuple[str, ...]) -> None:
        self.rows = rows
        self.columns = columns
        self.statements: list[tuple[str, list[Any] | None]] = []
        self.closed = False

    async def execute(self, statement: str, args: list[Any] | None = None) -> Result:
        self.statements.append((statement, args))
        return Result(rows=list(self.rows), columns=self.columns)

    async def close(self) -> None:
        self.closed = True


def test_read_only_accepts_reads() -> None:
    check_read_only("SELECT * FROM staging_items")
    check_read_only("  select 1")
    check_read_only("WITH one AS (SELECT 1) SELECT * FROM one")
    check_read_only("PRAGMA table_info(staging_items)")
    check_read_only("EXPLAIN SELECT 1")


def test_read_only_refuses_writes() -> None:
    for statement in (
        "INSERT INTO staging_items (id) VALUES ('x')",
        "update staging_items set state = 'ready'",
        "DELETE FROM staging_items",
        "DROP TABLE staging_items",
    ):
        with pytest.raises(ReadOnlyError):
            check_read_only(statement)


def test_read_only_refuses_a_write_hidden_after_a_cte() -> None:
    with pytest.raises(ReadOnlyError, match="delete"):
        check_read_only("WITH doomed AS (SELECT id FROM staging_items) DELETE FROM staging_items")


def test_read_only_ignores_a_write_word_inside_a_string() -> None:
    check_read_only("SELECT * FROM staging_items WHERE error = 'delete failed'")


def test_read_only_refuses_an_empty_statement() -> None:
    with pytest.raises(ReadOnlyError):
        check_read_only("   ")


async def test_database_passes_a_read_through() -> None:
    client = FakeClient([("deduped", 3054)], ("state", "rows"))
    database = Database(client, name="bank")

    result = await database.query("SELECT state, COUNT(*) AS rows FROM staging_items")

    assert result.columns == ("state", "rows")
    assert result.rows == (("deduped", 3054),)
    assert client.statements == [("SELECT state, COUNT(*) AS rows FROM staging_items", [])]


async def test_database_refuses_a_write_before_reaching_the_client() -> None:
    client = FakeClient([], ())
    database = Database(client, name="bank")

    with pytest.raises(ReadOnlyError):
        await database.query("DELETE FROM staging_items")

    assert client.statements == []


def test_query_result_maps_rows_to_columns() -> None:
    result = QueryResult(columns=("state", "rows"), rows=(("ready", 90), ("rejected", 172)))

    assert result.as_dicts() == [
        {"state": "ready", "rows": 90},
        {"state": "rejected", "rows": 172},
    ]
    assert len(result) == 2


def test_format_table_prints_a_header_and_rows() -> None:
    result = QueryResult(columns=("state", "rows"), rows=(("ready", 90),))

    table = format_table(result)

    assert "state" in table and "rows" in table
    assert "ready" in table and "90" in table
    assert format_table(QueryResult(columns=("state",), rows=())) == "(no rows)"


def test_parser_defaults_to_the_bank() -> None:
    args = build_parser().parse_args(["status"])

    assert args.database == "bank"
    assert args.json is False


def test_limit_is_bounded() -> None:
    assert _limit(50) == 50
    assert _limit(MAX_ROWS) == MAX_ROWS
    with pytest.raises(ConfigError):
        _limit(0)
    with pytest.raises(ConfigError):
        _limit(MAX_ROWS + 1)


def test_unknown_database_is_refused_by_the_parser() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--database", "other", "status"])
