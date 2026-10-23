"""The database client.

One class for both targets: a Turso url talks to the cloud over HTTP, anything
else is a local sqlite file. That is the whole reason the pipeline's
hand-rolled client was not carried forward, so there is one connection path to
reason about instead of two.

Statements use named parameters throughout. The pipeline built SQL by string
interpolation in four modules, which is how a `where` clause ends up being a
place where a value can escape into the statement.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Self

from utmelab_bank.errors import StoreError

__all__ = ["Store", "connect"]


class Store:
    """An open database, with every statement going through here.

    Wraps ``libsql_client`` so the rest of the package never sees its API. Only
    the handful of operations we actually use are exposed, which keeps the
    surface small enough that "all SQL lives in store/" is true.
    """

    def __init__(
        self,
        client: Any,
        url: str,
        token: str = "",
        *,
        read_only: bool = False,
    ) -> None:
        self._client = client
        self.url = url
        self.token = token
        #: A store told it is read-only refuses every write, so "we only read
        #: production" is a property of the object rather than of our self
        #: control. The token still has to be read-only too; this is the belt to
        #: the token's braces.
        self.read_only = read_only
        self._closed = False

    @classmethod
    async def open(
        cls,
        url: str,
        token: str = "",
        *,
        read_only: bool = False,
    ) -> Store:
        """Open a Turso url or a local sqlite path.

        A local path is given as ``sqlite:./x.db``. Anything with a scheme we do
        not recognise is an error rather than a guess, because silently treating
        a mistyped Turso url as a filename creates an empty database and every
        later check passes against nothing.
        """
        from libsql_client import create_client

        if not url:
            raise StoreError("no database url")

        lowered = url.lower()
        if lowered.startswith(("http://", "https://", "libsql://", "ws://", "wss://", "turso://")):
            if url.lower().startswith("turso://"):
                # libsql_client only accepts https://; turso:// is a shorthand
                # for the same Turso Cloud host with auth carried by ``token``.
                url = "https://" + url[len("turso://") :]
            client = create_client(url=url, auth_token=token or None)
        elif lowered.startswith(("sqlite:", "file:")):
            path = url.split(":", 1)[1]
            if path != ":memory:":
                target = Path(path).expanduser()
                target.parent.mkdir(parents=True, exist_ok=True)
                path = str(target)
            client = create_client(url=f"file:{path}")
        else:
            raise StoreError(
                "unrecognised database url",
                url=url,
                hint="use a libsql or https url, or a local path like sqlite:./bank.db",
            )

        return cls(client=client, url=url, token=token, read_only=read_only)

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        """Run one statement that changes something."""
        self._guard()
        self._guard_writable()
        try:
            await self._client.execute(sql, self._bind(params))
        except Exception as exc:
            raise StoreError("write failed", sql=_headline(sql), cause=exc) from exc

    async def execute_many(self, statements: list[tuple[str, dict[str, Any]]]) -> int:
        """Run statements in one round trip, all or nothing.

        Returns how many rows actually changed. That is not the same as the
        number of statements sent: an ``INSERT OR IGNORE`` for a row that is
        already there reports zero, and reporting twelve for a batch where
        nothing was new is how a re-scrape looks like it did work.

        Used by the tasks that write a batch of rows, so a 200 row promotion is
        one transaction rather than 200.
        """
        self._guard()
        self._guard_writable()
        if not statements:
            return 0
        try:
            results = await self._client.batch(
                [(sql, self._bind(params)) for sql, params in statements]
            )
        except Exception as exc:
            raise StoreError(
                "batch write failed",
                count=len(statements),
                sql=_headline(statements[0][0]),
                cause=exc,
            ) from exc
        return sum(int(getattr(result, "rows_affected", 0) or 0) for result in results)

    async def fetch_all(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Every row, as dicts keyed by column name."""
        self._guard()
        try:
            result = await self._client.execute(sql, self._bind(params))
        except Exception as exc:
            raise StoreError("read failed", sql=_headline(sql), cause=exc) from exc
        return [dict(zip(result.columns, row, strict=True)) for row in result.rows]

    async def fetch_one(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        rows = await self.fetch_all(sql, params)
        return rows[0] if rows else None

    async def scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        """The first column of the first row, or ``None``."""
        row = await self.fetch_one(sql, params)
        if not row:
            return None
        return next(iter(row.values()), None)

    @staticmethod
    def _bind(params: dict[str, Any] | None) -> dict[str, Any]:
        """Refuse a parameter the driver cannot carry.

        It used to coerce a list to ``None``, which made ``id IN (:p)`` match
        nothing while looking like it had run. The driver has no list expansion,
        so a caller that wants ``IN`` has to build the placeholders itself, and
        a silent NULL here is how that gets discovered the hard way.
        """
        if not params:
            return {}
        for key, value in params.items():
            if isinstance(value, list | tuple | set):
                raise StoreError(
                    "the driver takes one value per parameter, not a list",
                    parameter=key,
                    hint="build one placeholder per element and bind each",
                )
        return dict(params)

    # -- shape probes -----------------------------------------------------
    #
    # These live here rather than in ``contract/check.py`` so that the rule "all
    # SQL lives in store/" stays absolute. The contract layer asks questions;
    # only this module spells them.

    async def table_columns(self, table: str) -> frozenset[str]:
        """The columns a table has, as the engine reports them."""
        rows = await self.fetch_all(f'PRAGMA table_info("{table}")')
        return frozenset(str(row.get("name", "")) for row in rows)

    async def table_exists(self, table: str) -> bool:
        return bool(await self.table_columns(table))

    async def count_rows(self, table: str) -> int:
        value = await self.scalar(f'SELECT COUNT(*) AS n FROM "{table}"')
        return int(value or 0)

    async def count_where(self, table: str, column: str, *, empty: bool) -> int:
        """How many rows have ``column`` empty, or how many have it filled.

        Named rather than taking a fragment, because a fragment here would be
        the one way to get interpolated sql into this package.
        """
        if empty:
            sql = (
                f'SELECT COUNT(*) AS n FROM "{table}" WHERE "{column}" IS NULL OR "{column}" = \'\''
            )
        else:
            sql = f'SELECT COUNT(*) AS n FROM "{table}" WHERE "{column}" IS NOT NULL AND "{column}" <> \'\''
        value = await self.scalar(sql)
        return int(value or 0)

    async def get_meta(self, key: str) -> str | None:
        """Read a ``meta`` row, or ``None`` when the table or the row is absent.

        ``meta`` is created by the API on its first boot, so a bank that the API
        has never seen has no such table. "Nobody stamped it" and "there is
        nothing to stamp into" mean the same thing to the caller, so both are
        ``None`` rather than an error.
        """
        if not await self.table_exists("meta"):
            return None
        row = await self.fetch_one("SELECT value FROM meta WHERE key = :key", {"key": key})
        if not row:
            return None
        return None if row.get("value") is None else str(row["value"])

    async def set_meta(self, key: str, value: str) -> None:
        """Write a ``meta`` row.

        ``meta`` belongs to the API and we only ever read it in the normal path.
        This exists for tests that need to stand in for a bank the API has
        already booted against.
        """
        await self.execute(
            "INSERT INTO meta (key, value) VALUES (:key, :value) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            {"key": key, "value": value},
        )

    def _guard(self) -> None:
        if self._closed:
            raise StoreError("the store is closed")

    def _guard_writable(self) -> None:
        if self.read_only:
            raise StoreError(
                "refusing to write through a read-only store",
                url=self.url,
                hint="a read-only store is for reading production, never for staging",
            )

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            await self._client.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()


def _headline(sql: str) -> str:
    """The first line of a statement, for an error message.

    A multi-line insert is unreadable in a traceback, and the table name is the
    only part anybody needs.
    """
    first = sql.strip().split("\n")[0]
    return first if len(first) <= 100 else first[:100]


async def connect(
    url: str,
    token: str = "",
    *,
    read_only: bool = False,
) -> Store:
    """Open a store. Named so callers read as intent, not as plumbing."""
    store = await Store.open(url, token, read_only=read_only)
    await asyncio.sleep(0)
    return store
