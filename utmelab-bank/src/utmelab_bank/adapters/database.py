"""Turso client factory.

Turso serves its own databases over HTTP. The driver that matches a Turso
database is ``turso_serverless``. The libSQL clients speak the libSQL dialect
and are the right choice for a libSQL database, not for a Turso one.

The driver is synchronous and DB-API shaped, so it is driven from one worker
thread. Two things follow from that:

- The connection lives in that thread. Every query runs in the same thread, so
  the driver keeps its thread affinity.
- A remote database drops connections. A transient disconnect is retried, because
  a flaky network is not a reason to fail a whole run.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from utmelab_bank.config import Settings

from .catalog import ProductionCatalogReader

#: Errors that mean the connection dropped, not that the query was wrong.
TRANSIENT = (
    "RemoteDisconnected",
    "ConnectionResetError",
    "ConnectionAbortedError",
    "ConnectionError",
    "TimeoutError",
    "IncompleteRead",
    "Software caused connection abort",
    "Remote end closed connection",
    "Temporary failure in name resolution",
    "Name or service not known",
    "nodename nor servname provided",
)


class DatabaseError(RuntimeError):
    """Raised when a database cannot be reached or is not configured."""


@dataclass(frozen=True)
class Result:
    """The rows a query returned."""

    rows: list[tuple[Any, ...]]


def _is_transient(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(marker in text for marker in TRANSIENT)


#: The statements that change the database and so need a commit.
#:
#: The driver opens a deferred transaction, so a write that is not committed
#: is rolled back when the connection closes. The check is on the first
#: word, which is where the verb always is in a statement this bank writes.
WRITE_VERBS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "create",
        "drop",
        "alter",
        "replace",
    }
)


def _is_write(statement: str) -> bool:
    """Whether this statement changes the database."""
    head = statement.lstrip().split(None, 1)
    if not head:
        return False
    verb = head[0].lower()
    if not verb.isalpha():
        return False
    return verb in WRITE_VERBS


class TursoClient:
    """An async face for the synchronous ``turso_serverless`` driver."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        retries: int = 3,
        backoff: float = 1.5,
    ) -> None:
        if not url:
            raise DatabaseError("no database url was configured")
        self._url = url
        self._token = token
        self._retries = retries
        self._backoff = backoff
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="turso")
        self._connection: Any = None

    def _connect(self) -> Any:
        if self._connection is not None:
            return self._connection
        try:
            import turso_serverless  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise DatabaseError("turso-serverless is not installed") from exc
        try:
            self._connection = turso_serverless.connect(
                self._url,
                auth_token=self._token or None,
            )
        except Exception as exc:  # pragma: no cover - network and auth errors
            raise DatabaseError(f"could not open {self._url}: {exc}") from exc
        return self._connection

    async def execute(
        self,
        statement: str,
        args: list[Any] | None = None,
        *,
        commit: bool | None = None,
    ) -> Result:
        """Run one query in the driver's thread, retrying a dropped connection.

        A statement that writes is committed before this returns. The driver
        opens a deferred transaction, so without that commit every write
        would be rolled back when the connection closed, and the write would
        look like it had worked to the connection that made it.

        Pass ``commit=False`` to keep the write open, and commit it later
        with :meth:`commit`. That is for a caller that makes many writes and
        wants them to land together, because a commit is a round trip and
        the round trip is about a second.
        """
        loop = asyncio.get_running_loop()
        last: BaseException | None = None
        for attempt in range(self._retries):

            def run() -> list[tuple[Any, ...]]:
                connection = self._connect()
                cursor = connection.execute(statement, args or [])
                return list(cursor.fetchall())

            try:
                rows = await loop.run_in_executor(self._executor, run)
            except DatabaseError:
                raise
            except Exception as exc:
                last = exc
                # The connection is gone. Drop it so the next attempt reconnects.
                self._connection = None
                if not _is_transient(exc) or attempt == self._retries - 1:
                    raise DatabaseError(f"query failed: {exc}") from exc
                await asyncio.sleep(self._backoff * (attempt + 1))
                continue
            if commit is True or (commit is None and _is_write(statement)):
                await self.commit()
            return Result(rows=rows)
        raise DatabaseError(f"query failed after {self._retries} attempts: {last}")

    async def commit(self) -> None:
        """Commit whatever the connection has open.

        A write is committed on its own, so this is only needed by a caller
        that made several writes and wants them to land together.
        """
        loop = asyncio.get_running_loop()

        def run() -> None:
            connection = self._connect()
            connection.commit()

        await loop.run_in_executor(self._executor, run)

    async def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is not None:
            await asyncio.get_running_loop().run_in_executor(self._executor, connection.close)
        self._executor.shutdown(wait=False)


def prod_client(settings: Settings) -> TursoClient:
    """Client for the production catalog. Read only."""
    return TursoClient(settings.prod_database_url, settings.prod_auth_token)


def bank_client(settings: Settings) -> TursoClient:
    """Client for the bank's own database."""
    return TursoClient(settings.bank_database_url, settings.bank_auth_token)


def catalog_reader(settings: Settings | None = None) -> ProductionCatalogReader:
    """A catalog reader bound to the production database."""
    from utmelab_bank.config import load_settings

    resolved = settings or load_settings()
    return ProductionCatalogReader(prod_client(resolved))


__all__ = [
    "DatabaseError",
    "Result",
    "TursoClient",
    "bank_client",
    "catalog_reader",
    "prod_client",
]
