import pytest

from utmelab_bank.config import ConfigError
from utmelab_bank.routing import select_routes


def test_image_routing_prefers_cloudflare_then_opencode() -> None:
    routes = select_routes(
        "image_description",
        environment={
            "CLOUDFLARE_ACCOUNT_ID_01": "account-1",
            "CLOUDFLARE_API_TOKEN_01": "cloudflare-secret",
            "NVIDIA_API_KEY": "nvidia-secret",
        },
    )

    assert [route.family for route in routes] == [
        "openai",
        "opencode",
        "opencode",
        "kilo",
        "openai",
    ]
    assert [route.model_id for route in routes] == [
        "@cf/meta/llama-4-scout-17b-16e-instruct",
        "opencode/nemotron-3.5-super-vl-free",
        "opencode/glm-5.3-flash-free",
        "kilo/nvidia/nemotron-3.5-super-vl:free",
        "nvidia/nemotron-3-ultra-550b-a55b",
    ]
    assert routes[0].base_url.endswith("accounts/account-1/ai/v1")
    assert "cloudflare-secret" not in repr(routes[0])


def test_text_routing_prefers_cloudflare_then_opencode_then_kilo() -> None:
    routes = select_routes(
        "question_explanation",
        environment={
            "CLOUDFLARE_ACCOUNT_ID_01": "account-1",
            "CLOUDFLARE_API_TOKEN_01": "cloudflare-secret",
            "NVIDIA_API_KEY": "nvidia-secret",
        },
    )

    assert [route.provider for route in routes] == [
        "cloudflare",
        "opencode",
        "kilo",
        "nvidia",
    ]
    assert routes[0].model_id == "@cf/meta/llama-4-scout-17b-16e-instruct"
    assert routes[-1].model_id == "nvidia/nemotron-3-ultra-550b-a55b"


def test_credential_free_routes_need_no_secret() -> None:
    routes = select_routes("question_explanation", environment={})

    assert [route.family for route in routes] == ["opencode", "kilo"]
    kilo = routes[-1]
    assert kilo.protocol == "opencode-cli"
    assert kilo.model_id == "kilo/kilo-auto/free"
    assert kilo.api_key == ""
    assert kilo.transport["command"] == "kilo"
    assert kilo.transport["args"] == [
        "run",
        "--auto",
        "--format",
        "json",
        "-m",
        "{model}",
    ]


def test_missing_task_is_a_configuration_error() -> None:
    with pytest.raises(ConfigError, match="no task route"):
        select_routes("unknown", environment={})
