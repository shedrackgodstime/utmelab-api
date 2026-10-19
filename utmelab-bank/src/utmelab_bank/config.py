"""One typed config, built explicitly.

The pipeline's config was a module-level singleton evaluated at import, so a
test that set an environment variable after import saw the old value and there
was no way to reload. Here nothing is built until :func:`load` is called, the
result is passed down explicitly, and ``Config.source()`` reports where each
value came from so a surprising setting can be traced.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utmelab_bank.errors import ConfigError

__all__ = [
    "Config",
    "Lane",
    "RepoRoot",
    "SinkName",
    "find_repo_root",
    "load",
]

SinkName = Literal["db", "json"]
Lane = Literal["raw", "work", "ready"]

#: Lane name to the table prefix every lane's tables carry.
LANE_PREFIX: Final[dict[str, str]] = {"raw": "raw_", "work": "work_", "ready": "ready_"}

#: `--target prod` in our vocabulary means the ready lane inside the bank
#: database. Moving those rows into the production tables the API reads is a
#: separate future task and is deliberately not here.
#: Flag name to the field it sets. A flag does not always share its field's
#: name, and ``config`` has to be able to say which is which.
FLAG_TO_FIELD: Final[dict[str, str]] = {
    "target": "lane",
    "sink": "sink",
    "local-database": "local_database",
    "log-level": "log_level",
}

TARGET_ALIASES: Final[dict[str, Lane]] = {
    "raw": "raw",
    "work": "work",
    "staging": "work",
    "ready": "ready",
    "prod": "ready",
}

#: Fields whose environment name is not the plain ``UTMELAB_BANK_`` prefix, in
#: priority order. The two databases follow the ecosystem's ``TURSO_`` names, so
#: one ``.env`` and one set of CI secrets serve both the API and the bank. The
#: bank's own store and the production read store are deliberately separate
#: names, so the only way the bank writes production is a deliberate edit.
#:
#: The production read token has no write-capable fallback: the bank accepts a
#: read-only credential or none, so a full-access token in the environment can
#: never be used to open production here.
FIELD_ENV: Final[dict[str, tuple[str, ...]]] = {
    "database_url": ("UTMELAB_BANK_DATABASE_URL", "TURSO_UTMELAB_BANK_DB_URL"),
    "database_token": ("UTMELAB_BANK_DATABASE_TOKEN", "TURSO_UTMELAB_BANK_DB_TOKEN"),
    "prod_database_url": ("UTMELAB_BANK_PROD_DATABASE_URL", "TURSO_DB_URL"),
    "prod_database_token": (
        "UTMELAB_BANK_PROD_DATABASE_TOKEN",
        "TURSO_DB_TOKEN_READONLY",
    ),
}

#: Never echoed by ``utmelab-bank config``. A report that prints a token puts it
#: in a CI log, where it lives forever.
SECRET_FIELDS: Final[frozenset[str]] = frozenset({"database_token", "prod_database_token"})


def env_names_for(field: str) -> tuple[str, ...]:
    """Every environment name that can set ``field``, most specific first."""
    return FIELD_ENV.get(field) or (f"UTMELAB_BANK_{field.upper()}",)


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up until a directory holding both ``src`` and ``utmelab-bank`` is found.

    The repository root is what makes ``src/store/schema.rs`` reachable and what
    makes ``var/`` mean the same thing locally and in a workflow. Falls back to
    the package's own parents when installed away from the tree.
    """
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "src" / "store" / "schema.rs").is_file():
            return candidate
    return Path(__file__).resolve().parents[3]


class RepoRoot(BaseModel):
    """Resolved once, because three subsystems need it and none should guess."""

    model_config = ConfigDict(frozen=True)

    path: Path

    @property
    def rust_schema(self) -> Path:
        """The API's contract file. Read here, never written."""
        return self.path / "src" / "store" / "schema.rs"

    @property
    def package(self) -> Path:
        """The bank package directory, ``<root>/utmelab-bank``."""
        return self.path / "utmelab-bank"

    @property
    def var(self) -> Path:
        """The only directory this package may write files into. Gitignored.

        Lives inside the package (``utmelab-bank/var``), never at the repo
        root: this package owns its run output, the API owns ``db/``.
        """
        return self.package / "var"

    @property
    def media_repo(self) -> Path:
        return self.var / "media-repo"

    @property
    def env_file(self) -> Path:
        """The local ``.env``, when a developer left one. Gitignored.

        Read only when it exists, and never allowed to override a real
        environment variable, so a workflow's secrets always beat a file on
        somebody's disk.
        """
        return self.package / ".env"


class Config(BaseModel):
    """Everything a task might need, resolved once and passed down."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    repo: RepoRoot
    sink: SinkName = "db"
    lane: Lane = "work"

    database_url: str = ""
    database_token: str = ""
    local_database: Path | None = None

    #: Read from production, never written. Only ``catalog`` uses it today. Kept
    #: in its own field, away from ``database_url``, so the bank's own store can
    #: never be production by a single forgotten flag.
    prod_database_url: str = ""
    prod_database_token: str = ""

    media_remote: str = ""
    media_branch: str = "main"
    media_upload_enabled: bool = False

    ai_model: str = "opencode/space-bunny-free"
    ai_image_model: str = ""
    #: A second, different image model. When set, a description is usable only
    #: when both models pass it. One model twice is not an independent witness,
    #: so a value equal to ``ai_image_model`` (or ``ai_model`` when that is
    #: empty) is ignored.
    ai_image_second_model: str = ""
    ai_concurrency: int = 4
    ai_timeout_secs: int = 180
    ai_max_attempts: int = 3

    http_timeout_secs: int = 30
    http_delay_secs: float = 2.0
    http_user_agent: str = "utmelab-bank/0.1 (educational project)"

    log_level: str = "info"
    on_error: Literal["stop", "skip", "retry"] = "retry"

    #: Which settings came from a flag rather than the environment.
    flags: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)

    @field_validator("sink", mode="before")
    @classmethod
    def _check_sink(cls, value: object) -> object:
        if value not in ("db", "json"):
            raise ValueError(f"sink must be db or json, got {value!r}")
        return value

    @field_validator("lane", mode="before")
    @classmethod
    def _check_lane(cls, value: object) -> object:
        if isinstance(value, str):
            resolved = TARGET_ALIASES.get(value.lower())
            if resolved is None:
                raise ValueError(f"unknown target {value!r}")
            return resolved
        return value

    @field_validator("ai_concurrency", "ai_max_attempts")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be at least 1")
        return value

    @property
    def table_prefix(self) -> str:
        return LANE_PREFIX[self.lane]

    def for_lane(self, lane: Lane) -> Config:
        """The same config pointed at another lane. Cheap, because it is frozen."""
        return self.model_copy(update={"lane": lane})

    def source(self) -> dict[str, str]:
        """Where each field came from, for ``utmelab-bank config``.

        Values that came from a flag are reported as ``flag``. Anything not in
        the environment and not flagged is ``default``, which is how a field
        that should have been set in CI shows up as wrong. A token is reported
        as ``set`` rather than echoed, so a config dump is safe to paste.
        """
        report: dict[str, str] = {}
        for field in type(self).model_fields:
            found = next(
                (name for name in env_names_for(field) if name in os.environ),
                None,
            )
            if found is not None:
                report[field] = "env:set" if field in SECRET_FIELDS else f"env:{os.environ[found]}"
                continue
            flag = next(
                (name for name, target in FLAG_TO_FIELD.items() if target == field),
                field,
            )
            if flag in self.flags:
                report[field] = f"flag:{self.flags[flag]}"
            else:
                report[field] = "default"
        return report

    def require_database(self) -> str:
        """The database url to open, or a refusal naming what is missing.

        A local database may be given as a bare path, as ``file:./bank.db`` or as
        ``sqlite:./bank.db``. All three are accepted because a person will type
        all three, and silently creating a file literally named
        ``sqlite:./bank.db`` is worse than accepting a synonym.
        """
        if self.local_database is not None:
            raw = str(self.local_database)
            if raw.startswith(("file:", "sqlite:", "http://", "https://", "libsql://")):
                return raw
            return f"file:{raw}"
        if not self.database_url:
            raise ConfigError(
                "no database configured",
                hint="set UTMELAB_BANK_DATABASE_URL, or pass --local-database <path>",
            )
        return self.database_url

    def require_prod(self) -> str:
        """The production **read** url, or a refusal naming what is missing.

        Separate from :meth:`require_database` on purpose. The only thing that
        reads production is the catalog, and it must never be handed the bank's
        own url or the reverse.
        """
        if not self.prod_database_url:
            raise ConfigError(
                "no production read database configured",
                hint="set TURSO_DB_URL (or UTMELAB_BANK_PROD_DATABASE_URL)",
            )
        return self.prod_database_url


def _load_env_file(root: RepoRoot) -> None:
    """Load ``utmelab-bank/.env`` when it exists, never overriding real env.

    Locally the file holds the two database urls. In CI the same names arrive as
    secrets and there is no file, so this is a no-op there. ``override=False``
    matters: a workflow's environment is the truth, and a stale file on disk is
    not allowed to win.
    """
    path = root.env_file
    if os.environ.get("UTMELAB_BANK_NO_DOTENV") == "1":
        return
    if not path.is_file():
        return
    from dotenv import load_dotenv

    load_dotenv(path, override=False)


def load(
    *,
    repo: Path | None = None,
    sink: str | None = None,
    target: str | None = None,
    local_database: Path | None = None,
    where: dict[str, str] | None = None,
) -> Config:
    """Build a config from the environment, then let the flags win.

    Raises :class:`ConfigError` on an unusable value rather than falling back
    to a default, so a typo in CI fails loudly at startup.
    """
    root = RepoRoot(path=repo.resolve() if repo else find_repo_root())
    _load_env_file(root)
    env = os.environ

    def env_str(name: str, default: str = "") -> str:
        return env.get(f"UTMELAB_BANK_{name}", default)

    def env_first(names: tuple[str, ...]) -> str:
        return next((env[name] for name in names if name in env), "")

    def env_int(name: str, default: int) -> int:
        raw = env.get(f"UTMELAB_BANK_{name}")
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ConfigError(f"UTMELAB_BANK_{name} is not an integer", value=raw) from exc

    def env_float(name: str, default: float) -> float:
        raw = env.get(f"UTMELAB_BANK_{name}")
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise ConfigError(f"UTMELAB_BANK_{name} is not a number", value=raw) from exc

    settings: dict[str, object] = {
        "repo": root,
        "database_url": env_first(FIELD_ENV["database_url"]),
        "database_token": env_first(FIELD_ENV["database_token"]),
        "prod_database_url": env_first(FIELD_ENV["prod_database_url"]),
        "prod_database_token": env_first(FIELD_ENV["prod_database_token"]),
        "media_remote": env_str("MEDIA_REMOTE"),
        "media_branch": env_str("MEDIA_BRANCH", "main"),
        "media_upload_enabled": env.get("UTMELAB_BANK_MEDIA_UPLOAD_ENABLED") == "1",
        "ai_model": env_str("AI_MODEL", "opencode/space-bunny-free"),
        "ai_image_model": env_str("AI_IMAGE_MODEL", ""),
        "ai_image_second_model": env_str("AI_IMAGE_SECOND_MODEL", ""),
        "ai_concurrency": env_int("AI_CONCURRENCY", 4),
        "ai_timeout_secs": env_int("AI_TIMEOUT_SECS", 180),
        "ai_max_attempts": env_int("AI_MAX_ATTEMPTS", 3),
        "http_timeout_secs": env_int("HTTP_TIMEOUT_SECS", 30),
        "http_delay_secs": env_float("HTTP_DELAY_SECS", 2.0),
        "log_level": env_str("LOG_LEVEL", "info"),
        "on_error": env.get("UTMELAB_BANK_ON_ERROR", "retry"),
    }
    if local_database is not None:
        settings["local_database"] = local_database
    if sink is not None:
        settings["sink"] = sink
    if target is not None:
        settings["lane"] = target

    return Config(**settings, flags=where or {})
