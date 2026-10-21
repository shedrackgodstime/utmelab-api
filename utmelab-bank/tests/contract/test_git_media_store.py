"""Contract tests for the Git-backed media store."""

import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from utmelab_bank.adapters.media import GitMediaStore
from utmelab_bank.domain.models import MediaAsset

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a4944415408d763f8ffffffff3f0005fe02fedcc1"
    "42899e0000000049454e44ae426082"
)


@pytest.fixture
def temp_repo() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def store(temp_repo: Path) -> GitMediaStore:
    return GitMediaStore(temp_repo, branch="main")


@pytest.fixture
def sample_png() -> bytes:
    return PNG_1X1


async def test_put_and_read(store: GitMediaStore, sample_png: bytes) -> None:
    asset = await store.put(
        sample_png,
        mime="image/png",
        source_url="https://example.com/test.png",
    )
    assert isinstance(asset, MediaAsset)
    assert asset.mime == "image/png"
    assert asset.byte_size == len(sample_png)
    assert asset.width == 1
    assert asset.height == 1
    assert str(asset.source_url) == "https://example.com/test.png"

    data = await store.read(asset.asset_id)
    assert data == sample_png
    assert await store.exists(asset.asset_id)


async def test_idempotent_put(store: GitMediaStore, sample_png: bytes) -> None:
    first = await store.put(sample_png, mime="image/png")
    second = await store.put(sample_png, mime="image/png")
    assert first.asset_id == second.asset_id


async def test_git_commit_created(store: GitMediaStore) -> None:
    await store.put(b"test data", mime="text/plain", source_url="https://example.com")
    result = subprocess.run(
        ["git", "log", "--oneline", "-n", "5"],
        cwd=store.repo_path,
        capture_output=True,
        text=True,
    )
    assert "Add media asset" in result.stdout
