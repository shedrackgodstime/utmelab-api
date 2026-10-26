import pytest

from utmelab_bank.adapters.providers import (
    MockProvider,
    OpenAICompatibleProvider,
    OpenCodeProvider,
    create_text_provider,
)
from utmelab_bank.adapters.providers.factory import (
    FailoverProvider,
    create_from_route,
    _is_retryable,
)
from utmelab_bank.adapters.providers.openai_compatible import OpenAICompatibleError
from utmelab_bank.adapters.providers.opencode import OpenCodeError
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


def test_config_provider_returns_failover_when_multiple_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = (
        ProviderRoute(
            task="question_explanation",
            model_key="model-1",
            provider="provider-1",
            protocol="openai-compatible",
            model_id="provider-1/model-1",
            account_id="acc-1",
            base_url="https://a.invalid",
            api_key="key-1",
        ),
        ProviderRoute(
            task="question_explanation",
            model_key="model-2",
            provider="provider-2",
            protocol="openai-compatible",
            model_id="provider-2/model-2",
            account_id="acc-2",
            base_url="https://b.invalid",
            api_key="key-2",
        ),
    )
    monkeypatch.setattr(
        "utmelab_bank.adapters.providers.factory.select_routes", lambda task: routes
    )

    provider = create_text_provider("config", settings=settings(), task="question_explanation")

    assert isinstance(provider, FailoverProvider)


def test_config_provider_returns_single_route_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = ProviderRoute(
        task="question_explanation",
        model_key="model-1",
        provider="provider-1",
        protocol="openai-compatible",
        model_id="provider-1/model-1",
        account_id="acc-1",
        base_url="https://a.invalid",
        api_key="key-1",
    )
    monkeypatch.setattr(
        "utmelab_bank.adapters.providers.factory.select_routes", lambda task: (route,)
    )

    provider = create_text_provider("config", settings=settings(), task="question_explanation")

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.producer.model == "provider-1/model-1"


def test_is_retryable_recognizes_categories() -> None:
    assert _is_retryable(OpenAICompatibleError("rate limited", category="rate_limit"))
    assert _is_retryable(OpenCodeError("quota exceeded", category="quota"))
    assert _is_retryable(OpenAICompatibleError("timeout", category="timeout"))
    assert _is_retryable(OpenCodeError("upstream", category="upstream"))
    assert _is_retryable(OpenAICompatibleError("transport fail", category="transport"))
    assert _is_retryable(OpenAICompatibleError("503", category="provider_unavailable", status=503))

    # Non-retryable
    assert not _is_retryable(OpenAICompatibleError("bad auth", category="authentication"))
    assert not _is_retryable(OpenCodeError("invalid request", category="invalid_request"))
    assert not _is_retryable(OpenAICompatibleError("bad output", category="output"))
    assert not _is_retryable(OpenCodeError("schema fail", category="output_schema"))

    # 5xx status without category
    class StatusError(Exception):
        status = 502

    assert _is_retryable(StatusError("502"))
