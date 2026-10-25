import pytest

from utmelab_bank.adapters.providers import MockProvider, OpenCodeProvider, create_text_provider
from utmelab_bank.config import ConfigError, Settings


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


def test_factory_rejects_unknown_provider_without_fallback() -> None:
    with pytest.raises(ConfigError, match="unknown provider"):
        create_text_provider("unknown", settings=settings())
