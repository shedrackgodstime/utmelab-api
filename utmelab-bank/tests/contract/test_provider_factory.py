import pytest

from utmelab_bank.adapters.providers import (
    MockProvider,
    OpenAICompatibleProvider,
    OpenCodeProvider,
    create_text_provider,
)
from utmelab_bank.adapters.providers.factory import create_from_route
from utmelab_bank.config import ConfigError, Settings
from utmelab_bank.routing import ProviderRoute


def settings() -> Settings:
    return Settings(
        prod_database_url="turso://prod",
        prod_auth_token="readonly",
        bank_database_url="turso://bank",
        bank_auth_token="bank",
        ai_model="opencode/test-model",
    )


def test_factory_builds_mock_provider() -> None:
    provider = create_text_provider("mock", settings=settings())

    assert isinstance(provider, MockProvider)
    assert provider.producer.provider == "mock"


def test_factory_builds_opencode_with_configured_model() -> None:
    provider = create_text_provider("opencode", settings=settings())

    assert isinstance(provider, OpenCodeProvider)
    assert provider.producer.model == "opencode/test-model"


def test_factory_builds_openai_compatible_provider_from_nvidia_settings() -> None:
    values = settings().__dict__.copy()
    values.update(nvidia_api_key="nvidia-key", openai_model="meta/test-model")
    configured = Settings(**values)

    provider = create_text_provider("openai", settings=configured)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.producer.model == "meta/test-model"


def test_factory_rejects_unknown_provider_without_fallback() -> None:
    with pytest.raises(ConfigError, match="unknown provider"):
        create_text_provider("unknown", settings=settings())


def test_route_builds_the_openai_compatible_adapter() -> None:
    route = ProviderRoute(
        task="question_explanation",
        model_key="nvidia-model",
        provider="nvidia",
        protocol="openai-compatible",
        model_id="nvidia/test-model",
        account_id="nvidia-01",
        base_url="https://example.invalid/v1",
        api_key="secret",
    )

    provider = create_from_route(route)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.producer.model == "nvidia/test-model"


def test_route_builds_the_opencode_cli_adapter() -> None:
    route = ProviderRoute(
        task="question_explanation",
        model_key="deepseek",
        provider="opencode",
        protocol="opencode-cli",
        model_id="opencode/deepseek-v4.1-flash-free",
        account_id="opencode-local",
        base_url="",
        api_key="",
        transport={
            "command": "opencode",
            "args": ["run", "--format", "json", "-m", "{model}"],
        },
    )

    provider = create_from_route(route)

    assert isinstance(provider, OpenCodeProvider)
    assert provider.producer.model == "opencode/deepseek-v4.1-flash-free"


def test_route_rejects_an_unknown_protocol() -> None:
    route = ProviderRoute(
        task="question_explanation",
        model_key="mystery",
        provider="mystery",
        protocol="mystery",
        model_id="mystery/model",
        account_id="mystery-01",
        base_url="",
        api_key="",
    )

    with pytest.raises(ConfigError, match="unknown provider protocol"):
        create_from_route(route)
