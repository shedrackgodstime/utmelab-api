"""The media settings and the factories that read them."""

from __future__ import annotations

import asyncio

import pytest

from utmelab_bank.adapters.media import (
    DescribeImageConsensus,
    GitLabMediaStore,
    InsufficientWitnesses,
    LocalMediaStore,
    MediaError,
    create_configured_describer,
    create_describer,
    create_media_store,
)
from utmelab_bank.adapters.providers import OpenAICompatibleProvider
from utmelab_bank.config import DEFAULT_MEDIA_BASE_URL, ConfigError, Settings
from utmelab_bank.routing import ProviderRoute, TaskPolicy, task_policy


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "prod_database_url": "turso://prod",
        "prod_auth_token": "ro",
        "bank_database_url": "turso://bank",
        "bank_auth_token": "bank",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_the_base_is_the_assets_host() -> None:
    settings = _settings(gitlab_token="tok", gitlab_media_repo="group/media")
    assert settings.media_base == DEFAULT_MEDIA_BASE_URL


def test_a_self_hosted_host_and_branch_are_honoured() -> None:
    settings = _settings(
        gitlab_token="tok",
        gitlab_media_repo="g/m",
        gitlab_host="gitlab.example",
        media_branch="figures",
    )
    assert settings.gitlab_host == "gitlab.example"
    assert settings.media_branch == "figures"
    # The storage host and branch do not change the served url.
    assert settings.media_base == DEFAULT_MEDIA_BASE_URL


def test_an_explicit_base_wins_and_is_normalised() -> None:
    settings = _settings(media_base_url="https://cdn.example/figs/")
    assert settings.media_base == "https://cdn.example/figs"


def test_without_a_token_or_repo_the_store_is_local() -> None:
    store = create_media_store(_settings())
    assert isinstance(store, LocalMediaStore)


def test_a_token_without_a_repo_is_refused() -> None:
    with pytest.raises(MediaError, match="both a token and a repo"):
        create_media_store(_settings(gitlab_token="tok"))


def test_a_repo_without_a_token_is_refused() -> None:
    with pytest.raises(MediaError, match="both a token and a repo"):
        create_media_store(_settings(gitlab_media_repo="g/m"))


def test_a_token_and_repo_build_the_gitlab_store() -> None:
    settings = _settings(
        gitlab_token="tok",
        gitlab_media_repo="g/m",
    )
    store = create_media_store(settings)
    assert isinstance(store, GitLabMediaStore)
    assert store.host == "gitlab.com"
    assert store.project == "g/m"
    assert store.branch == "main"
    assert store.base_url == DEFAULT_MEDIA_BASE_URL
    asyncio.run(store.close())


def test_the_describer_is_a_two_witness_consensus() -> None:
    describer = create_describer()
    assert isinstance(describer, DescribeImageConsensus)
    witnesses = describer._describers
    assert len(witnesses) == 2
    assert witnesses[0].producer.model != witnesses[1].producer.model


def test_mock_is_not_a_selectable_describer() -> None:
    """A double that answers without a model must not be reachable in the product."""
    with pytest.raises(ValueError, match="Unknown describer"):
        create_describer(provider="mock")


def test_openai_compatible_describer_builds_two_witnesses() -> None:
    describer = create_describer(
        provider="openai",
        model="vision/one",
        second_model="vision/two",
        api_key="test-key",
        base_url="https://example.test/v1",
    )
    assert isinstance(describer, DescribeImageConsensus)
    assert all(isinstance(witness, OpenAICompatibleProvider) for witness in describer._describers)


def test_one_model_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="two different models"):
        create_describer(model="opencode/x", second_model="opencode/x")


def _route(model_id: str, *, account: str = "account-01") -> ProviderRoute:
    return ProviderRoute(
        task="image_description",
        model_key=model_id,
        provider="nvidia",
        protocol="openai-compatible",
        model_id=model_id,
        account_id=account,
        base_url="https://example.test/v1",
        api_key="test-key",
    )


def _policy(**overrides: object) -> TaskPolicy:
    base: dict[str, object] = {
        "task": "image_description",
        "strategy": "consensus",
        "on_insufficient_witnesses": "block",
        "minimum_successful_witnesses": 2,
        "require_distinct_models": True,
    }
    base.update(overrides)
    return TaskPolicy(**base)  # type: ignore[arg-type]


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    routes: tuple[ProviderRoute, ...],
    *,
    policy: TaskPolicy | None = None,
) -> None:
    monkeypatch.setattr("utmelab_bank.adapters.media.describe.select_routes", lambda task: routes)
    chosen = policy or _policy()
    monkeypatch.setattr("utmelab_bank.adapters.media.describe.task_policy", lambda task: chosen)


def test_the_configured_describer_takes_one_witness_per_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second key for one model is not a second witness."""
    _configure(
        monkeypatch,
        (
            _route("vision/one", account="account-01"),
            _route("vision/one", account="account-02"),
            _route("vision/one", account="account-03"),
            _route("vision/two", account="account-01"),
        ),
    )

    describer = create_configured_describer()

    assert isinstance(describer, DescribeImageConsensus)
    witnesses = describer._describers
    assert [witness.producer.model for witness in witnesses] == ["vision/one", "vision/two"]
    assert len({witness.producer.model for witness in witnesses}) == len(witnesses)


def test_one_model_on_two_keys_cannot_witness_a_figure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old routes[:2] slice built this pair, and it could never describe."""
    _configure(
        monkeypatch,
        (
            _route("vision/one", account="account-01"),
            _route("vision/one", account="account-02"),
        ),
    )

    with pytest.raises(InsufficientWitnesses, match="needs 2 distinct model witnesses"):
        create_configured_describer()


def test_no_usable_route_is_a_named_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, ())

    with pytest.raises(InsufficientWitnesses) as raised:
        create_configured_describer()

    assert raised.value.context["resolved"] == 0
    assert raised.value.context["required"] == 2
    assert raised.value.is_retryable is False


def test_the_configured_witness_count_is_obeyed(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(
        monkeypatch,
        (
            _route("vision/one"),
            _route("vision/two"),
            _route("vision/three"),
            _route("vision/four"),
        ),
        policy=_policy(minimum_successful_witnesses=3),
    )

    describer = create_configured_describer()

    assert len(describer._describers) == 3


def test_a_policy_that_cannot_be_a_consensus_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        (_route("vision/one"), _route("vision/two")),
        policy=_policy(strategy="first_available"),
    )

    with pytest.raises(ConfigError, match="only 'consensus'"):
        create_configured_describer()


def test_the_shipped_routing_file_declares_the_consensus_policy() -> None:
    """The describer's rules come from the file, and the file says all three."""
    assert task_policy("image_description") == _policy()


def test_a_policy_without_distinct_models_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(
        monkeypatch,
        (_route("vision/one"), _route("vision/two")),
        policy=_policy(require_distinct_models=False),
    )

    with pytest.raises(ConfigError, match="distinct models"):
        create_configured_describer()


def test_a_policy_that_does_not_block_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(
        monkeypatch,
        (_route("vision/one"), _route("vision/two")),
        policy=_policy(on_insufficient_witnesses="continue"),
    )

    with pytest.raises(ConfigError, match="on_insufficient_witnesses"):
        create_configured_describer()
