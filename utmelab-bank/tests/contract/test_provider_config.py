import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[2]
PROVIDERS = ROOT / "config" / "providers"
SCHEMA = ROOT / "config" / "schema" / "provider.schema.json"
ROUTING = ROOT / "config" / "routing.json"
ROUTING_SCHEMA = ROOT / "config" / "schema" / "routing.schema.json"


@pytest.mark.parametrize("name", ["openai.json", "opencode.json"])
def test_provider_manifest_matches_its_schema(name: str) -> None:
    config = json.loads((PROVIDERS / name).read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    errors = sorted(Draft202012Validator(schema).iter_errors(config), key=str)

    assert not errors, "\n".join(error.message for error in errors)


@pytest.mark.parametrize("name", ["openai.json", "opencode.json"])
def test_provider_manifest_has_no_task_routing(name: str) -> None:
    config = json.loads((PROVIDERS / name).read_text(encoding="utf-8"))

    assert "tasks" not in config


def test_routing_matches_its_schema() -> None:
    routing = json.loads(ROUTING.read_text(encoding="utf-8"))
    schema = json.loads(ROUTING_SCHEMA.read_text(encoding="utf-8"))

    errors = sorted(Draft202012Validator(schema).iter_errors(routing), key=str)

    assert not errors, "\n".join(error.message for error in errors)


@pytest.mark.parametrize("name", ["openai.json", "opencode.json"])
def test_provider_manifest_never_contains_secret_values(name: str) -> None:
    text = (PROVIDERS / name).read_text(encoding="utf-8")

    assert 'NVIDIA_API_KEY="' not in text
    assert 'CLOUDFLARE_API_TOKEN_01="' not in text
