"""The media settings and the factories that read them."""

from __future__ import annotations

import asyncio

import pytest

from utmelab_bank.adapters.media import (
    DescribeImageConsensus,
    GitLabMediaStore,
    LocalMediaStore,
    MediaError,
    create_describer,
    create_media_store,
)
from utmelab_bank.adapters.providers import OpenAICompatibleProvider
from utmelab_bank.config import DEFAULT_MEDIA_BASE_URL, Settings


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
    describer = create_describer(provider="mock")
    assert isinstance(describer, DescribeImageConsensus)


def test_openai_compatible_describer_builds_two_witnesses() -> None:
    describer = create_describer(
        provider="openai",
        model="vision/one",
        second_model="vision/two",
        api_key="test-key",
        base_url="https://example.test/v1",
    )
    assert isinstance(describer, DescribeImageConsensus)
    assert all(
        isinstance(witness, OpenAICompatibleProvider) for witness in describer._describers
    )


def test_one_model_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="two different models"):
        create_describer(model="opencode/x", second_model="opencode/x")
