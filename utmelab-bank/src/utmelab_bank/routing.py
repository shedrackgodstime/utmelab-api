"""Validated, secret-free routing for the provider manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from .config import BANK_ROOT, ConfigError, _read_env

MANIFEST_PATH = BANK_ROOT / "openai.config"
SCHEMA_PATH = BANK_ROOT / "schemas" / "openai.config.schema.json"


@dataclass(frozen=True)
class ProviderRoute:
    """A resolved route with its secret held only in memory."""

    task: str
    model_key: str
    provider: str
    model_id: str
    account_id: str
    base_url: str
    api_key: str = field(repr=False)


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Load and validate the routing manifest before any provider is opened."""
    if not path.is_file():
        raise ConfigError(f"provider manifest is missing: {path}")
    try:
        manifest = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        schema_path = path.parent / "schemas" / "openai.config.schema.json"
        schema = cast(dict[str, Any], json.loads(schema_path.read_text(encoding="utf-8")))
        errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=str)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"provider manifest cannot be read: {path}") from exc
    if errors:
        detail = "; ".join(error.message for error in errors[:3])
        raise ConfigError(f"provider manifest is invalid: {detail}")
    _validate_references(manifest)
    return manifest


def select_routes(
    task: str,
    *,
    manifest: dict[str, Any] | None = None,
    environment: dict[str, str] | None = None,
) -> tuple[ProviderRoute, ...]:
    """Resolve usable routes for a task in priority order.

    Missing credentials, disabled accounts, disabled models and disallowed
    model statuses are skipped. Nothing falls back to a secret from another
    environment variable, and no secret is returned in logs or repr output.
    """
    config = manifest or load_manifest()
    env = environment if environment is not None else _read_env()
    task_config = config["tasks"].get(task)
    if task_config is None:
        raise ConfigError(f"provider manifest has no task route: {task}")
    if not task_config.get("enabled", False):
        return ()

    allowed_statuses = set(task_config.get("allowed_model_statuses", ()))
    routes: list[ProviderRoute] = []
    for candidate in sorted(task_config.get("candidates", ()), key=lambda item: item["priority"]):
        model_key = candidate["model"]
        model = config["models"][model_key]
        if model.get("status") not in allowed_statuses:
            continue
        provider_name = model["provider"]
        provider = config["providers"][provider_name]
        if provider.get("status") != "enabled":
            continue
        pool_name = candidate["account_pool"]
        if pool_name != provider["account_pool"]:
            raise ConfigError(f"task {task!r} routes model {model_key!r} to the wrong account pool")
        for account in sorted(config["accounts"][pool_name], key=lambda item: item["priority"]):
            if not account.get("enabled") or not account.get("authorized"):
                continue
            api_key = env.get(account["api_key_env"], "")
            if not api_key:
                continue
            base_url = provider["base_url"]
            account_id_env = account.get("account_id_env")
            if "{account_id}" in base_url:
                account_id = env.get(account_id_env or "", "")
                if not account_id:
                    continue
                base_url = base_url.replace("{account_id}", account_id)
            else:
                account_id = account["id"]
            routes.append(
                ProviderRoute(
                    task=task,
                    model_key=model_key,
                    provider=provider_name,
                    model_id=model["model_id"],
                    account_id=account["id"],
                    base_url=base_url,
                    api_key=api_key,
                )
            )
    return tuple(routes)


def _validate_references(manifest: dict[str, Any]) -> None:
    """Reject cross-section references that JSON Schema cannot express simply."""
    providers = manifest["providers"]
    accounts = manifest["accounts"]
    models = manifest["models"]
    for model_key, model in models.items():
        provider_name = model.get("provider")
        if provider_name not in providers:
            raise ConfigError(f"model {model_key!r} references unknown provider {provider_name!r}")
    for task_name, task in manifest["tasks"].items():
        for candidate in task.get("candidates", ()):
            model_key = candidate.get("model")
            pool_name = candidate.get("account_pool")
            if model_key not in models:
                raise ConfigError(f"task {task_name!r} references unknown model {model_key!r}")
            if pool_name not in accounts:
                raise ConfigError(
                    f"task {task_name!r} references unknown account pool {pool_name!r}"
                )


__all__ = ["MANIFEST_PATH", "ProviderRoute", "load_manifest", "select_routes"]
