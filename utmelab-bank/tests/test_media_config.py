"""The media settings and the factories that read them."""

from __future__ import annotations

import pytest

from utmelab_bank.adapters.media import (
    DescribeImageConsensus,
    create_describer,
    create_media_store,
)
from utmelab_bank.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "prod_database_url": "turso://prod",
        "prod_auth_token": "ro",
        "bank_database_url": "turso://bank",
        "bank_auth_token": "bank",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_the_remote_and_base_derive_from_the_repo() -> None:
    settings = _settings(gitlab_token="tok", gitlab_media_repo="group/media")
    assert settings.media_remote == "https://oauth2:tok@gitlab.com/group/media.git"
    assert settings.media_base == "https://gitlab.com/group/media/-/raw/main/images"


def test_a_self_hosted_host_and_branch_are_honoured() -> None:
    settings = _settings(
        gitlab_token="tok",
        gitlab_media_repo="g/m",
        gitlab_host="gitlab.example",
        media_branch="figures",
    )
    assert settings.media_remote == "https://oauth2:tok@gitlab.example/g/m.git"
    assert settings.media_base == "https://gitlab.example/g/m/-/raw/figures/images"


def test_no_repo_means_local_only() -> None:
    settings = _settings()
    assert settings.media_remote == ""
    assert settings.media_base == ""
    assert settings.media_upload_enabled is False


def test_an_explicit_base_wins_and_is_normalised() -> None:
    settings = _settings(gitlab_media_repo="g/m", media_base_url="https://cdn.example/figs/")
    assert settings.media_base == "https://cdn.example/figs"


def test_create_media_store_reads_the_settings() -> None:
    settings = _settings(
        gitlab_token="tok",
        gitlab_media_repo="g/m",
        media_upload_enabled=True,
    )
    store = create_media_store(settings)
    assert store.remote == "https://oauth2:tok@gitlab.com/g/m.git"
    assert store.base_url == "https://gitlab.com/g/m/-/raw/main/images"
    assert store.root == settings.media_repo_path
    assert store.upload_enabled is True


def test_the_describer_is_a_two_witness_consensus() -> None:
    describer = create_describer(provider="mock")
    assert isinstance(describer, DescribeImageConsensus)


def test_one_model_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="two different models"):
        create_describer(model="opencode/x", second_model="opencode/x")
