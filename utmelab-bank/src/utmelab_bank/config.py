"""Settings for utmelab-bank.

One file holds the answers: ``utmelab-bank/.env``. Real environment variables
always win over the file, so a deployment can inject them instead.

Two databases, two jobs, and they must never be confused.

- The **production** database holds the catalog. It is read only. The catalog
  is the authority for topic placement, so we read it and never write to it.
- The **bank** database is ours. It holds the staging rows while they are
  built, enriched and checked.

Both are Turso databases, reached over the wire with ``turso_serverless``,
which is the driver that matches the Turso engine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: The bank package root. Everything the bank owns lives under it.
BANK_ROOT = Path(__file__).resolve().parents[2]

#: Where local state belongs. Never the parent directory.
VAR_DIR = BANK_ROOT / "var"

#: The one file that holds the answers.
ENV_FILE = BANK_ROOT / ".env"

#: The variables the bank reads, and what each one is for.
PROD_DATABASE_URL = "TURSO_PROD_DATABASE_URL"
PROD_AUTH_TOKEN = "TURSO_PROD_AUTH_TOKEN"
PROD_READONLY_TOKEN = "TURSO_PROD_AUTH_TOKEN_READONLY"
BANK_DATABASE_URL = "TURSO_BANK_DATABASE_URL"
BANK_AUTH_TOKEN = "TURSO_BANK_AUTH_TOKEN"
GITLAB_TOKEN = "GITLAB_TOKEN"
NVIDIA_API_KEY = "NVIDIA_API_KEY"


class ConfigError(RuntimeError):
    """Raised when a required setting is missing or unusable."""


def _parse_env_file(path: Path) -> dict[str, str]:
    """Read a .env file. Only KEY=VALUE lines, no quoting games."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _read_env() -> dict[str, str]:
    """The file first, then the real environment, which wins."""
    values = _parse_env_file(ENV_FILE)
    for key, value in os.environ.items():
        if value:
            values[key] = value
    return values


@dataclass(frozen=True)
class Settings:
    """Where everything lives."""

    prod_database_url: str
    prod_auth_token: str
    bank_database_url: str
    bank_auth_token: str
    gitlab_token: str | None = None
    nvidia_api_key: str | None = None

    @property
    def var_dir(self) -> Path:
        """The bank's own working directory."""
        return VAR_DIR


def load_settings(*, require: bool = True) -> Settings:
    """Read the settings from the environment and ``utmelab-bank/.env``.

    With ``require=False`` the production pair may be missing. That is for
    tests and for a developer who only wants to run against fixtures.
    """
    values = _read_env()

    prod_url = values.get(PROD_DATABASE_URL, "")
    prod_token = values.get(PROD_AUTH_TOKEN, "") or values.get(PROD_READONLY_TOKEN, "")
    bank_url = values.get(BANK_DATABASE_URL, "")
    bank_token = values.get(BANK_AUTH_TOKEN, "")

    if prod_url and not prod_token:
        raise ConfigError(f"the production catalog needs a read only token: set {PROD_AUTH_TOKEN}")
    if require and not prod_url:
        raise ConfigError(
            "the production catalog database is not configured: set "
            f"{PROD_DATABASE_URL} in {ENV_FILE}"
        )
    if require and not bank_url:
        raise ConfigError(
            f"the bank database is not configured: set {BANK_DATABASE_URL} in {ENV_FILE}"
        )

    return Settings(
        prod_database_url=prod_url,
        prod_auth_token=prod_token,
        bank_database_url=bank_url,
        bank_auth_token=bank_token,
        gitlab_token=values.get(GITLAB_TOKEN) or None,
        nvidia_api_key=values.get(NVIDIA_API_KEY) or None,
    )
