"""The Turso client. The commit contract, which is where the data goes.

The driver opens a deferred transaction, so a write that is not committed is
rolled back when the connection closes. A write that looks like it worked,
to the connection that made it, and is gone by the next one, is the worst
kind of bug, so the client commits every write and these tests pin that.
"""

from __future__ import annotations

from typing import Any

import pytest

from utmelab_bank.adapters.database import Result, TursoClient, _is_transient, _is_write


class FakeConnection:
    """A connection that records what was done to it."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, list[Any]]] = []
        self.commits = 0
        self.closed = False

    def execute(self, statement: str, args: Any = ()) -> Any:
        self.executed.append((statement, list(args)))

        class Cursor:
            def __init__(self, rows: list[tuple[Any, ...]]) -> None:
                self._rows = rows

            def fetchall(self) -> list[tuple[Any, ...]]:
                return self._rows

        return Cursor([("ok",)])

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def turso() -> tuple[TursoClient, FakeConnection]:
    connection = FakeConnection()
    client = TursoClient("turso://example", "token")
    client._connection = connection
    return client, connection


async def test_a_write_is_committed(turso: tuple[TursoClient, FakeConnection]) -> None:
    client, connection = turso

    await client.execute("INSERT INTO t VALUES (1)")

    assert connection.commits == 1


async def test_a_read_is_not_committed(
    turso: tuple[TursoClient, FakeConnection],
) -> None:
    client, connection = turso

    await client.execute("SELECT 1")

    assert connection.commits == 0


async def test_a_write_can_be_left_open(
    turso: tuple[TursoClient, FakeConnection],
) -> None:
    """A caller that writes in a batch commits it once, at the end."""
    client, connection = turso

    await client.execute("INSERT INTO t VALUES (1)", commit=False)

    assert connection.commits == 0

    await client.commit()

    assert connection.commits == 1


async def test_a_read_can_be_committed_on_request(
    turso: tuple[TursoClient, FakeConnection],
) -> None:
    client, connection = turso

    await client.execute("SELECT 1", commit=True)

    assert connection.commits == 1


async def test_the_result_carries_the_rows(
    turso: tuple[TursoClient, FakeConnection],
) -> None:
    client, _ = turso

    result = await client.execute("SELECT 1")

    assert isinstance(result, Result)
    assert result.rows == [("ok",)]


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO t VALUES (1)",
        "insert into t values (1)",
        "  UPDATE t SET a = 1",
        "DELETE FROM t",
        "CREATE TABLE IF NOT EXISTS t (a TEXT)",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN b TEXT",
        "INSERT OR REPLACE INTO t VALUES (1)",
    ],
)
def test_the_write_verbs_are_recognised(statement: str) -> None:
    assert _is_write(statement) is True


def test_turso_stream_expiry_is_retried() -> None:
    assert _is_transient(RuntimeError("HTTP status 404: stream not found: abc")) is True


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT 1",
        "select * from t",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "PRAGMA table_info(t)",
        "",
        "   ",
    ],
)
def test_the_read_statements_are_not_writes(statement: str) -> None:
    assert _is_write(statement) is False
