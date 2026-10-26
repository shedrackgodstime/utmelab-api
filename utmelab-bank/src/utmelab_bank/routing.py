"""Validated, secret-free routing for provider manifests and task priorities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from .config import BANK_ROOT, ConfigError, _read_env

#: Point the bank at an editable config directory instead of the packaged copy.
CONFIG_DIR_ENV = "UTMELAB_BANK_CONFIG_DIR"


def _resolve_config_dir() -> Path:
    """Use an explicit override, the source checkout, or the packaged copy."""
    override = _read_env().get(CONFIG_DIR_ENV)
    if override:
        return Path(override)
    source = BANK_ROOT / "config"
    if (BANK_ROOT / "src" / "utmelab_bank").is_dir() and source.is_dir():
        return source
    packaged = Path(__file__).resolve().parent / "config_data"
    if packaged.is_dir():
        return packaged
    return source


CONFIG_DIR = _resolve_config_dir()
PROVIDERS_DIR = CONFIG_DIR / "providers"
SCHEMA_DIR = CONFIG_DIR / "schema"
SCHEMA_PATH = SCHEMA_DIR / "provider.schema.json"
ROUTING_SCHEMA_PATH = SCHEMA_DIR / "routing.schema.json"
ROUTING_PATH = CONFIG_DIR / "routing.json"
MANIFEST_PATH = PROVIDERS_DIR / "openai.json"
OPENCODE_MANIFEST_PATH = PROVIDERS_DIR / "opencode.json"

#: The authentication kinds a provider manifest may declare.
AUTH_KINDS = ("env", "cli", "none")


@dataclass(frozen=True)
class ProviderRoute:
    """A resolved route with its secret held only in memory."""

    task: str
    model_key: str
    provider: str
    protocol: str
    model_id: str
    account_id: str
    base_url: str
    api_key: str = field(repr=False)
    transport: dict[str, Any] = field(default_factory=dict, repr=False)
    family: str = ""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"{label} is missing: {path}")
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{label} cannot be read: {path}") from exc


def _validate(instance: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _load_json(schema_path, f"{label} schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=str)
    if errors:
        detail = "; ".join(error.message for error in errors[:3])
        raise ConfigError(f"{label} is invalid: {detail}")


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Load and validate one provider manifest."""
    manifest = _load_json(path, "provider manifest")
    _validate(manifest, SCHEMA_PATH, "provider manifest")
    _validate_provider_references(manifest)
    return manifest


def load_providers() -> dict[str, dict[str, Any]]:
    """Load every provider family, keyed by its file stem."""
    paths = sorted(PROVIDERS_DIR.glob("*.json"))
    if not paths:
        raise ConfigError(f"no provider manifests in {PROVIDERS_DIR}")
    return {path.stem: load_manifest(path) for path in paths}


def load_routing(path: Path = ROUTING_PATH) -> dict[str, Any]:
    """Load and validate the global task routing."""
    routing = _load_json(path, "provider routing")
    _validate(routing, ROUTING_SCHEMA_PATH, "provider routing")
    return routing


def select_routes(
    task: str,
    *,
    routing: dict[str, Any] | None = None,
    manifests: dict[str, dict[str, Any]] | None = None,
    environment: dict[str, str] | None = None,
) -> tuple[ProviderRoute, ...]:
    """Resolve usable routes for a task in priority order.

    Missing credentials, disabled accounts, disabled models and disallowed
    model statuses are skipped. Nothing falls back to a secret from another
    environment variable, and no secret is returned in logs or repr output.
    """
    if routing is None:
        routing = load_routing()
    if manifests is None:
        manifests = load_providers()
    _validate_routing_references(routing, manifests)
    env = environment if environment is not None else _read_env()
    task_config = routing["tasks"].get(task)
    if task_config is None:
        raise ConfigError(f"provider routing has no task route: {task}")
    if not task_config.get("enabled", False):
        return ()

    allowed_statuses = set(task_config.get("allowed_model_statuses", ()))
    routes: list[ProviderRoute] = []
    for candidate in sorted(task_config.get("candidates", ()), key=lambda item: item["priority"]):
        family = candidate["provider"]
        manifest = manifests[family]
        model_key = candidate["model"]
        model = manifest["models"][model_key]
        if model.get("status") not in allowed_statuses:
            continue
        provider_name = model["provider"]
        provider = manifest["providers"][provider_name]
        if provider.get("status") != "enabled":
            continue
        protocol = provider["protocol"]
        auth_kind = provider.get("auth", {}).get("kind", "env")
        transport: dict[str, Any] = dict(provider.get("transport", {}))
        base_url_template = provider.get("base_url", "")
        pool_name = provider["account_pool"]
        for account in sorted(manifest["accounts"][pool_name], key=lambda item: item["priority"]):
            if not account.get("enabled") or not account.get("authorized"):
                continue
            if auth_kind == "env":
                api_key_env = account.get("api_key_env")
                if not api_key_env:
                    raise ConfigError(
                        f"account {account['id']!r} needs api_key_env for environment auth"
                    )
                api_key = env.get(api_key_env, "")
                if not api_key:
                    continue
            else:
                api_key = ""
            base_url = base_url_template
            if "{account_id}" in base_url:
                account_id_env = account.get("account_id_env")
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
                    protocol=protocol,
                    model_id=model["model_id"],
                    account_id=account["id"],
                    base_url=base_url,
                    api_key=api_key,
                    transport=transport,
                    family=family,
                )
            )
    return tuple(routes)


def _validate_provider_references(manifest: dict[str, Any]) -> None:
    """Reject cross-section references that JSON Schema cannot express simply."""
    providers = manifest["providers"]
    accounts = manifest["accounts"]
    models = manifest["models"]
    for model_key, model in models.items():
        provider_name = model.get("provider")
        if provider_name not in providers:
            raise ConfigError(f"model {model_key!r} references unknown provider {provider_name!r}")
    for provider_name, provider in providers.items():
        auth_kind = provider.get("auth", {}).get("kind", "env")
        if auth_kind not in AUTH_KINDS:
            raise ConfigError(f"provider {provider_name!r} has unknown auth kind {auth_kind!r}")
        pool_name = provider.get("account_pool")
        if pool_name is None:
            continue
        if pool_name not in accounts:
            raise ConfigError(
                f"provider {provider_name!r} references unknown account pool {pool_name!r}"
            )
        if auth_kind == "env":
            for account in accounts[pool_name]:
                if not account.get("api_key_env"):
                    raise ConfigError(
                        f"account {account.get('id')!r} in pool {pool_name!r} needs api_key_env"
                    )


def _validate_routing_references(
    routing: dict[str, Any], manifests: dict[str, dict[str, Any]]
) -> None:
    """Reject routing candidates that name a missing provider or model."""
    for task_name, task in routing["tasks"].items():
        for candidate in task.get("candidates", ()):
            family = candidate.get("provider")
            if family not in manifests:
                raise ConfigError(
                    f"task {task_name!r} references unknown provider family {family!r}"
                )
            model_key = candidate.get("model")
            if model_key not in manifests[family]["models"]:
                raise ConfigError(
                    f"task {task_name!r} references unknown model {model_key!r} "
                    f"in provider {family!r}"
                )


__all__ = [
    "CONFIG_DIR",
    "CONFIG_DIR_ENV",
    "MANIFEST_PATH",
    "OPENCODE_MANIFEST_PATH",
    "PROVIDERS_DIR",
    "ROUTING_PATH",
    "ROUTING_SCHEMA_PATH",
    "SCHEMA_PATH",
    "ProviderRoute",
    "load_manifest",
    "load_providers",
    "load_routing",
    "select_routes",
]
