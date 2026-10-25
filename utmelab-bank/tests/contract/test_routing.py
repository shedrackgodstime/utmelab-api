import pytest

from utmelab_bank.config import ConfigError
from utmelab_bank.routing import load_manifest, select_routes


def test_manifest_resolves_only_authorized_configured_image_routes() -> None:
    routes = select_routes(
        "image_description",
        manifest=load_manifest(),
        environment={
            "CLOUDFLARE_ACCOUNT_ID_01": "account-1",
            "CLOUDFLARE_API_TOKEN_01": "cloudflare-secret",
            "NVIDIA_API_KEY": "nvidia-secret",
        },
    )

    assert [route.model_id for route in routes] == [
        "@cf/meta/llama-4-scout-17b-16e-instruct"
    ]
    assert routes[0].base_url.endswith("accounts/account-1/ai/v1")
    assert "cloudflare-secret" not in repr(routes[0])


def test_manifest_prioritizes_nvidia_for_text_tasks() -> None:
    routes = select_routes(
        "question_explanation",
        manifest=load_manifest(),
        environment={
            "CLOUDFLARE_ACCOUNT_ID_01": "account-1",
            "CLOUDFLARE_API_TOKEN_01": "cloudflare-secret",
            "NVIDIA_API_KEY": "nvidia-secret",
        },
    )

    assert routes[0].provider == "nvidia"
    assert routes[1].provider == "cloudflare"


def test_missing_task_is_a_configuration_error() -> None:
    with pytest.raises(ConfigError, match="no task route"):
        select_routes("unknown", manifest=load_manifest(), environment={})
