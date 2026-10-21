"""Contract tests for the Git-backed media store.

The offline proof uses a real bare git remote and a real clone, because the
thing being tested is the handoff between the clone on disk, the remote, and
the url the row will carry. A mock git would prove none of them.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from tests.media_fakes import PNG_1X1
from utmelab_bank.adapters.media import (
    GitMediaStore,
    MediaAuthError,
    MediaError,
    name_for,
)

BASE = "https://gitlab.com/group/media/-/raw/main/images"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _remote(tmp_path: Path) -> Path:
    """A bare remote with a seed commit on ``main``."""
    bare = tmp_path / "media.git"
    _git(tmp_path, "init", "--bare", str(bare))
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.name", "test")
    _git(seed, "config", "user.email", "test@test")
    (seed / "README").write_text("media\n", encoding="utf-8")
    _git(seed, "add", "--all")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "origin", "main")
    return bare


def _identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give git an identity through the environment, as a runner does."""
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "bank")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "bank@utmelab.local")


def _local(tmp_path: Path, *, base_url: str = "") -> GitMediaStore:
    return GitMediaStore(tmp_path / "media", branch="main", base_url=base_url)


def test_put_writes_a_content_addressed_blob(tmp_path: Path) -> None:
    store = _local(tmp_path)
    asset = asyncio.run(
        store.put(PNG_1X1, mime="image/png", source_url="https://example.com/test.png")
    )

    assert asset.mime == "image/png"
    assert asset.byte_size == len(PNG_1X1)
    assert asset.width == 1
    assert asset.height == 1
    assert str(asset.source_url) == "https://example.com/test.png"
    # No base url, so the row gets the bare name, which cannot go into an
    # inline. That is the "cannot serve yet" branch, not a mistake.
    assert asset.storage_url == name_for(asset.asset_id, ".png")

    assert asyncio.run(store.read(asset.asset_id)) == PNG_1X1
    assert asyncio.run(store.exists(asset.asset_id))
    assert asyncio.run(store.exists("0" * 64)) is False


def test_a_base_url_makes_the_url_servable(tmp_path: Path) -> None:
    store = _local(tmp_path, base_url=BASE)
    asset = asyncio.run(store.put(PNG_1X1, mime="image/png"))
    assert asset.storage_url == f"{BASE}/{asset.asset_id}.png"


def test_idempotent_put(tmp_path: Path) -> None:
    store = _local(tmp_path)
    first = asyncio.run(store.put(PNG_1X1, mime="image/png"))
    second = asyncio.run(store.put(PNG_1X1, mime="image/png"))
    assert first.asset_id == second.asset_id


def test_a_local_put_records_a_commit(tmp_path: Path) -> None:
    store = _local(tmp_path)
    asyncio.run(store.put(PNG_1X1, mime="image/png"))
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=store.root, capture_output=True, text=True
    )
    assert "media: publish fetched figures" in log.stdout


def test_publish_lands_the_bytes_and_proves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A green put means a fresh clone has the figure."""
    _identity(monkeypatch)
    bare = _remote(tmp_path)
    store = GitMediaStore(
        tmp_path / "clone",
        remote=str(bare),
        branch="main",
        base_url=BASE,
        upload_enabled=True,
    )

    asset = asyncio.run(
        store.put(PNG_1X1, mime="image/png", source_url="https://cdn.example/figure.png")
    )

    assert asset.storage_url == f"{BASE}/{asset.asset_id}.png"

    verify = tmp_path / "verify"
    _git(tmp_path, "clone", "--branch", "main", str(bare), str(verify))
    landed = verify / "images" / f"{asset.asset_id}.png"
    assert landed.is_file(), "green said published, and the remote disagrees"
    assert landed.read_bytes() == PNG_1X1


def test_a_push_refused_by_the_credential_is_not_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _identity(monkeypatch)
    bare = _remote(tmp_path)
    hook = bare / "hooks" / "pre-receive"
    hook.write_text(
        '#!/bin/sh\necho "remote: HTTP Basic: Access denied." >&2\nexit 1\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    store = GitMediaStore(
        tmp_path / "clone", remote=str(bare), branch="main", upload_enabled=True, attempts=1
    )

    with pytest.raises(MediaAuthError) as caught:
        asyncio.run(store.put(PNG_1X1, mime="image/png"))

    assert caught.value.is_retryable is False


def test_a_push_that_fails_for_another_reason_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _identity(monkeypatch)
    bare = _remote(tmp_path)
    hook = bare / "hooks" / "pre-receive"
    hook.write_text('#!/bin/sh\necho "declined" >&2\nexit 1\n', encoding="utf-8")
    hook.chmod(0o755)
    store = GitMediaStore(
        tmp_path / "clone", remote=str(bare), branch="main", upload_enabled=True, attempts=1
    )

    with pytest.raises(MediaError) as caught:
        asyncio.run(store.put(PNG_1X1, mime="image/png"))

    assert caught.value.is_retryable is True
    assert caught.value.context["attempts"] == 1
