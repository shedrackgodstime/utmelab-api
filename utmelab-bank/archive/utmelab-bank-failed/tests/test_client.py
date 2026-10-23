"""The store's own contract: one connection, one place for SQL, no writes when
it was opened for reading.

The client is small on purpose. Tests here hold the boundary the rest of the
package assumes: values are bound, list parameters are refused rather than
silently dropped, and a read-only store cannot be written through.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from utmelab_bank.errors import StoreError
from utmelab_bank.store.client import Store


async def test_open_refuses_an_empty_url() -> None:
    with pytest.raises(StoreError, match="no database url"):
        await Store.open("")


async def test_open_refuses_an_unknown_scheme() -> None:
    with pytest.raises(StoreError, match="unrecognised database url"):
        await Store.open("postgres://example/db")


async def test_open_creates_a_local_database_and_its_directory(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "bank.db"

    store = await Store.open(f"sqlite:{db}")
    try:
        assert db.parent.is_dir()
        assert await store.scalar("SELECT 1 AS one") == 1
    finally:
        await store.aclose()


async def test_a_turso_url_is_rewritten_to_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class FakeClient:
        async def close(self) -> None:
            return None

    def fake_create_client(*, url: str, auth_token: str | None = None) -> FakeClient:
        seen["url"] = url
        seen["token"] = auth_token
        return FakeClient()

    import libsql_client

    monkeypatch.setattr(libsql_client, "create_client", fake_create_client)

    store = await Store.open("turso://example.turso.io", "secret")

    assert seen == {"url": "https://example.turso.io", "token": "secret"}
    await store.aclose()


async def test_read_write_and_probes(tmp_path: Path) -> None:
    store = await Store.open(f"sqlite:{tmp_path / 'client.db'}")
    try:
        await store.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
        await store.execute("INSERT INTO t (id, v) VALUES (:id, :v)", {"id": "a", "v": "one"})
        await store.execute("INSERT INTO t (id, v) VALUES ('b', NULL)")

        assert await store.fetch_one("SELECT * FROM t WHERE id = :id", {"id": "a"}) == {
            "id": "a",
            "v": "one",
        }
        assert await store.fetch_one("SELECT * FROM t WHERE id = 'missing'") is None
        assert await store.scalar("SELECT v FROM t WHERE id = 'a'") == "one"
        assert await store.scalar("SELECT v FROM t WHERE id = 'missing'") is None
        assert await store.count_rows("t") == 2
        assert await store.count_where("t", "v", empty=False) == 1
        assert await store.count_where("t", "v", empty=True) == 1
        assert await store.table_exists("t")
        assert "id" in await store.table_columns("t")
        assert await store.fetch_all("SELECT id FROM t ORDER BY id") == [{"id": "a"}, {"id": "b"}]
    finally:
        await store.aclose()


async def test_execute_many_counts_changed_rows(tmp_path: Path) -> None:
    store = await Store.open(f"sqlite:{tmp_path / 'client.db'}")
    try:
        await store.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")

        changed = await store.execute_many(
            [
                ("INSERT INTO t (id, v) VALUES (:id, :v)", {"id": "a", "v": "1"}),
                ("INSERT OR IGNORE INTO t (id, v) VALUES (:id, :v)", {"id": "a", "v": "2"}),
            ]
        )

        assert changed == 1
        assert await store.execute_many([]) == 0
    finally:
        await store.aclose()


async def test_a_list_parameter_is_refused_not_dropped(tmp_path: Path) -> None:
    store = await Store.open(f"sqlite:{tmp_path / 'client.db'}")
    try:
        await store.execute("CREATE TABLE t (id TEXT)")
        with pytest.raises(StoreError, match="one value per parameter"):
            await store.fetch_all("SELECT * FROM t WHERE id IN (:ids)", {"ids": ["a", "b"]})
    finally:
        await store.aclose()


async def test_a_read_only_store_refuses_writes(tmp_path: Path) -> None:
    db = tmp_path / "client.db"
    writer = await Store.open(f"sqlite:{db}")
    await writer.execute("CREATE TABLE t (id TEXT)")
    await writer.aclose()

    reader = await Store.open(f"sqlite:{db}", read_only=True)
    try:
        assert await reader.fetch_all("SELECT * FROM t") == []
        with pytest.raises(StoreError, match="read-only"):
            await reader.execute("INSERT INTO t (id) VALUES ('a')")
    finally:
        await reader.aclose()


async def test_a_closed_store_refuses_every_call(tmp_path: Path) -> None:
    store = await Store.open(f"sqlite:{tmp_path / 'client.db'}")
    await store.aclose()
    await store.aclose()

    with pytest.raises(StoreError, match="closed"):
        await store.fetch_all("SELECT 1")


async def test_the_context_manager_closes_the_store(tmp_path: Path) -> None:
    async with await Store.open(f"sqlite:{tmp_path / 'client.db'}") as store:
        assert await store.scalar("SELECT 1 AS one") == 1

    with pytest.raises(StoreError, match="closed"):
        await store.fetch_all("SELECT 1")


async def test_meta_is_absent_until_the_api_creates_it(tmp_path: Path) -> None:
    store = await Store.open(f"sqlite:{tmp_path / 'client.db'}")
    try:
        assert await store.get_meta("contract_version") is None

        await store.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        assert await store.get_meta("contract_version") is None

        await store.set_meta("contract_version", "1")
        assert await store.get_meta("contract_version") == "1"

        await store.set_meta("contract_version", "2")
        assert await store.get_meta("contract_version") == "2"
    finally:
        await store.aclose()
