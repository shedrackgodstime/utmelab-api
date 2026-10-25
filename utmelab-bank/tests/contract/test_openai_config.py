import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[2]


def test_openai_config_matches_its_schema() -> None:
    config = json.loads((ROOT / "openai.config").read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas" / "openai.config.schema.json").read_text(encoding="utf-8")
    )

    errors = sorted(Draft202012Validator(schema).iter_errors(config), key=str)

    assert not errors, "\n".join(error.message for error in errors)


def test_openai_config_never_contains_secret_values() -> None:
    text = (ROOT / "openai.config").read_text(encoding="utf-8")

    assert "NVIDIA_API_KEY=\"" not in text
    assert "CLOUDFLARE_API_TOKEN_01=\"" not in text
