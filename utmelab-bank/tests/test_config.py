"""The two databases, the ``.env``, and the promise that config never leaks.

The bank writes its own database and reads production. Those are two urls, and
the whole point of this file is that they can never collapse into one: the day
they do, a forgotten flag stages rows into the serving database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utmelab_bank.config import load
from utmelab_bank.errors import ConfigError, StoreError
from utmelab_bank.store.client import Store


def test_the_bank_and_production_urls_come_from_separate_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TURSO_UTMELAB_BANK_DB_URL", "libsql://bank")
    monkeypatch.setenv("TURSO_DB_URL", "libsql://prod")
    config = load(repo=tmp_path)
    assert config.database_url == "libsql://bank"
    assert config.prod_database_url == "libsql://prod"


def test_the_production_token_prefers_the_read_only_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TURSO_DB_TOKEN", "write-capable")
    monkeypatch.setenv("TURSO_DB_TOKEN_READONLY", "read-only")
    config = load(repo=tmp_path)
    assert config.prod_database_token == "read-only"


def test_production_falls_back_to_the_only_token_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TURSO_DB_TOKEN", "only-one")
    config = load(repo=tmp_path)
    assert config.prod_database_token == "only-one"


def test_require_prod_refuses_when_nothing_is_configured(tmp_path: Path) -> None:
    config = load(repo=tmp_path)
    with pytest.raises(ConfigError, match="production read database"):
        config.require_prod()


def test_the_config_report_never_echoes_a_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TURSO_UTMELAB_BANK_DB_TOKEN", "sekret-bank")
    monkeypatch.setenv("TURSO_DB_TOKEN", "sekret-prod")
    report = load(repo=tmp_path).source()
    assert report["database_token"] == "env:set"
    assert report["prod_database_token"] == "env:set"
    assert not any("sekret" in value for value in report.values())


def test_the_env_file_is_read_when_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("UTMELAB_BANK_NO_DOTENV", raising=False)
    package = tmp_path / "utmelab-bank"
    package.mkdir()
    (package / ".env").write_text(
        "TURSO_UTMELAB_BANK_DB_URL=libsql://from-file\nTURSO_DB_URL=libsql://prod-from-file\n",
        encoding="utf-8",
    )
    config = load(repo=tmp_path)
    assert config.database_url == "libsql://from-file"
    assert config.prod_database_url == "libsql://prod-from-file"


def test_a_real_env_variable_beats_the_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("UTMELAB_BANK_NO_DOTENV", raising=False)
    monkeypatch.setenv("TURSO_DB_URL", "libsql://from-env")
    package = tmp_path / "utmelab-bank"
    package.mkdir()
    (package / ".env").write_text("TURSO_DB_URL=libsql://from-file\n", encoding="utf-8")
    config = load(repo=tmp_path)
    assert config.prod_database_url == "libsql://from-env"


async def test_a_read_only_store_refuses_to_write(tmp_path: Path) -> None:
    """The belt to the read-only token's braces: the object itself says no."""
    store = await Store.open(f"sqlite:{tmp_path / 'ro.db'}", read_only=True)
    try:
        with pytest.raises(StoreError, match="read-only"):
            await store.execute("CREATE TABLE t (id TEXT)")
    finally:
        await store.aclose()
