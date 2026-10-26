import pytest

from utmelab_bank.config import ConfigError
from utmelab_bank.routing import select_routes


def test_image_routing_prefers_openai_then_opencode() -> None:
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
        "openai",
        "opencode",
        "opencode",
    ]
    assert [route.model_id for route in routes] == [
        "@cf/meta/llama-4-scout-17b-16e-instruct",
        "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "opencode/nemotron-3.5-super-vl-free",
        "opencode/glm-5.3-flash-free",
    ]
    assert routes[0].base_url.endswith("accounts/account-1/ai/v1")
    assert "cloudflare-secret" not in repr(routes[0])


def test_text_routing_prefers_opencode_then_nvidia_then_cloudflare() -> None:
    routes = select_routes(
        "question_explanation",
        environment={
            "CLOUDFLARE_ACCOUNT_ID_01": "account-1",
            "CLOUDFLARE_API_TOKEN_01": "cloudflare-secret",
            "NVIDIA_API_KEY": "nvidia-secret",
        },
    )

    assert [route.family for route in routes] == ["opencode", "openai", "openai"]
    assert [route.provider for route in routes] == ["opencode", "nvidia", "cloudflare"]
    assert routes[0].model_id == "opencode/deepseek-v4.1-flash-free"


def test_opencode_route_needs_no_secret() -> None:
    routes = select_routes("question_explanation", environment={})

    assert len(routes) == 1
    route = routes[0]
    assert route.family == "opencode"
    assert route.protocol == "opencode-cli"
    assert route.model_id == "opencode/deepseek-v4.1-flash-free"
    assert route.api_key == ""
    assert route.transport["command"] == "opencode"
    assert route.transport["args"] == ["run", "--format", "json", "-m", "{model}"]


def test_missing_task_is_a_configuration_error() -> None:
    with pytest.raises(ConfigError, match="no task route"):
        select_routes("unknown", environment={})
