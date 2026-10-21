"""Tests for the settings layer and the Turso client."""

from pathlib import Path

import pytest

from utmelab_bank.adapters.database import Result, TursoClient
from utmelab_bank import config as config_module
from utmelab_bank.config import _parse_env_file as parse_env_file
from utmelab_bank.config import (
    BANK_ROOT,
    ENV_FILE,
    ConfigError,
    load_settings,
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real .env file must not decide what a test sees."""
    monkeypatch.setattr(config_module, "_parse_env_file", lambda path: {})


def test_settings_read_the_bank_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TURSO_PROD_DATABASE_URL", "turso://prod.example")
    monkeypatch.setenv("TURSO_PROD_AUTH_TOKEN", "prod-token")
    monkeypatch.setenv("TURSO_BANK_DATABASE_URL", "turso://bank.example")
    monkeypatch.setenv("TURSO_BANK_AUTH_TOKEN", "bank-token")
    monkeypatch.setenv("GITLAB_TOKEN", "glpat")

    settings = load_settings()

    assert settings.prod_database_url == "turso://prod.example"
    assert settings.prod_auth_token == "prod-token"
    assert settings.bank_database_url == "turso://bank.example"
    assert settings.bank_auth_token == "bank-token"
    assert settings.gitlab_token == "glpat"


def test_settings_require_the_production_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ConfigError, match="production catalog"):
        load_settings()


def test_settings_require_the_bank_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TURSO_PROD_DATABASE_URL", "turso://prod.example")
    monkeypatch.setenv("TURSO_PROD_AUTH_TOKEN", "prod-token")
    monkeypatch.delenv("TURSO_BANK_DATABASE_URL", raising=False)
    monkeypatch.setenv("TURSO_BANK_AUTH_TOKEN", "bank-token")

    with pytest.raises(ConfigError, match="bank database"):
        load_settings()


def test_settings_refuse_a_prod_url_without_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TURSO_PROD_DATABASE_URL", "turso://prod.example")
    monkeypatch.delenv("TURSO_PROD_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("TURSO_BANK_DATABASE_URL", "turso://bank.example")
    monkeypatch.setenv("TURSO_BANK_AUTH_TOKEN", "bank-token")

    with pytest.raises(ConfigError, match="read only token"):
        load_settings()


def test_the_env_file_lives_inside_the_bank() -> None:
    assert ENV_FILE.parent == BANK_ROOT
    assert ENV_FILE.name == ".env"


def test_local_state_lives_inside_the_bank() -> None:
    from utmelab_bank.config import VAR_DIR

    assert VAR_DIR.parent == BANK_ROOT
    assert VAR_DIR.name == "var"


def test_env_file_parsing(tmp_path: Path) -> None:

    path = tmp_path / ".env"
    path.write_text(
        "# a comment\n"
        "\n"
        "TURSO_PROD_DATABASE_URL=turso://prod.example\n"
        'GITLAB_TOKEN="glpat-quoted"\n'
        "MALFORMED_LINE\n",
        encoding="utf-8",
    )

    values = parse_env_file(path)

    assert values["TURSO_PROD_DATABASE_URL"] == "turso://prod.example"
    assert values["GITLAB_TOKEN"] == "glpat-quoted"
    assert "MALFORMED_LINE" not in values


def test_turso_client_needs_a_url() -> None:
    with pytest.raises(Exception, match="url"):
        TursoClient("", "token")


def test_result_carries_rows() -> None:
    result = Result(rows=[("a", 1)])
    assert result.rows == [("a", 1)]
