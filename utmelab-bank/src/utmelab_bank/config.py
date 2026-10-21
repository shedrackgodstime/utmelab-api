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
#: The production token the bank uses, and the only one it will accept.
#:
#: Read only, on purpose. The bank never writes production, so a write
#: capable token must not be usable here, and there is no fallback to one.
PROD_READONLY_TOKEN = "TURSO_PROD_AUTH_TOKEN_READONLY"
BANK_DATABASE_URL = "TURSO_BANK_DATABASE_URL"
BANK_AUTH_TOKEN = "TURSO_BANK_AUTH_TOKEN"
GITLAB_TOKEN = "GITLAB_TOKEN"
NVIDIA_API_KEY = "NVIDIA_API_KEY"

#: The GitLab project that holds the figure bytes, ``group/project``.
GITLAB_MEDIA_REPO = "GITLAB_MEDIA_REPO"
#: The GitLab host. Self-hosted instances set this.
GITLAB_HOST = "GITLAB_HOST"
#: The branch the media project publishes to.
MEDIA_BRANCH = "UTMELAB_BANK_MEDIA_BRANCH"
#: The url prefix a served figure gets. Overrides the default assets host.
MEDIA_BASE_URL = "UTMELAB_BANK_MEDIA_BASE_URL"
#: The served url prefix. The bytes may live on GitLab, but the row carries
#: this host; pointing the domain at GitLab is a DNS change, not a rewrite.
DEFAULT_MEDIA_BASE_URL = "https://assets.utmelab.com/images"

#: The model that tags, explains and verifies.
AI_MODEL = "UTMELAB_BANK_AI_MODEL"
#: The two models that witness a figure. They must differ: one model twice is
#: not an independent witness.
AI_IMAGE_MODEL = "UTMELAB_BANK_AI_IMAGE_MODEL"
AI_IMAGE_SECOND_MODEL = "UTMELAB_BANK_AI_IMAGE_SECOND_MODEL"

#: What we have today. Two different free models on the OpenCode provider,
#: both picked for vision work; swap them in ``.env`` without touching code.
DEFAULT_AI_MODEL = "opencode/deepseek-v4.1-flash-free"
DEFAULT_AI_IMAGE_MODEL = "opencode/nemotron-3.5-super-vl-free"
DEFAULT_AI_IMAGE_SECOND_MODEL = "opencode/glm-5.3-flash-free"


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
    #: ``group/project`` of the GitLab media project.
    gitlab_media_repo: str | None = None
    gitlab_host: str = "gitlab.com"
    media_branch: str = "main"
    #: An explicit served url prefix. Defaults to the assets host.
    media_base_url: str | None = None
    ai_model: str = DEFAULT_AI_MODEL
    ai_image_model: str = DEFAULT_AI_IMAGE_MODEL
    ai_image_second_model: str = DEFAULT_AI_IMAGE_SECOND_MODEL

    @property
    def var_dir(self) -> Path:
        """The bank's own working directory."""
        return VAR_DIR

    @property
    def media_repo_path(self) -> Path:
        """Where a local run stores figures when no remote is configured."""
        return VAR_DIR / "media"

    @property
    def media_base(self) -> str:
        """The url prefix a served figure gets.

        The bank records the bare name ``<sha>.<ext>``; this is the prefix the
        row's inline gets. It points at the assets host, not the storage host,
        so moving the bytes from GitLab to somewhere else is a DNS change.
        """
        return (self.media_base_url or DEFAULT_MEDIA_BASE_URL).rstrip("/")


def load_settings(*, require: bool = True) -> Settings:
    """Read the settings from the environment and ``utmelab-bank/.env``.

    With ``require=False`` the production pair may be missing. That is for
    tests and for a developer who only wants to run against fixtures.
    """
    values = _read_env()

    prod_url = values.get(PROD_DATABASE_URL, "")
    # Read only, and only read only. A write capable token is not a fallback.
    prod_token = values.get(PROD_READONLY_TOKEN, "")
    bank_url = values.get(BANK_DATABASE_URL, "")
    bank_token = values.get(BANK_AUTH_TOKEN, "")

    if prod_url and not prod_token:
        raise ConfigError(
            f"the production catalog needs a read only token: set {PROD_READONLY_TOKEN}"
        )
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
        gitlab_media_repo=values.get(GITLAB_MEDIA_REPO) or None,
        gitlab_host=values.get(GITLAB_HOST) or "gitlab.com",
        media_branch=values.get(MEDIA_BRANCH) or "main",
        media_base_url=values.get(MEDIA_BASE_URL) or None,
        ai_model=values.get(AI_MODEL) or DEFAULT_AI_MODEL,
        ai_image_model=values.get(AI_IMAGE_MODEL) or DEFAULT_AI_IMAGE_MODEL,
        ai_image_second_model=(values.get(AI_IMAGE_SECOND_MODEL) or DEFAULT_AI_IMAGE_SECOND_MODEL),
    )
