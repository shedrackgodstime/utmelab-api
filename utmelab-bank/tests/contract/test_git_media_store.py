import asyncio
import tempfile
from pathlib import Path

import pytest

from utmelab_pipeline.adapters.media import GitMediaStore
from utmelab_pipeline.domain.models import MediaAsset


class TestGitMediaStore:
    @pytest.fixture
    def temp_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def store(self, temp_repo):
        return GitMediaStore(temp_repo, branch="main")

    @pytest.fixture
    def sample_png(self) -> bytes:
        # Minimal valid PNG (1x1 transparent)
        return bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000a4944415408d763f8ffffffff3f0005fe02fedcc1"
            "42899e0000000049454e44ae426082"
        )

    async def test_put_and_read(self, store: GitMediaStore, sample_png: bytes):
        asset = await store.put(sample_png, mime="image/png", source_url="https://example.com/test.png")
        assert isinstance(asset, MediaAsset)
        assert asset.mime == "image/png"
        assert asset.byte_size == len(sample_png)
        assert asset.width == 1
        assert asset.height == 1
        assert str(asset.source_url) == "https://example.com/test.png"
        assert asset.asset_id == asset.asset_id

        # Read back
        data = await store.read(asset.asset_id)
        assert data == sample_png

        # Exists check
        assert await store.exists(asset.asset_id)

    async def test_idempotent_put(self, store: GitMediaStore, sample_png: bytes):
        asset1 = await store.put(sample_png, mime="image/png")
        asset2 = await store.put(sample_png, mime="image/png")
        assert asset1.asset_id == asset2.asset_id

    async def test_git_commit_created(self, store: GitMediaStore, sample_png: bytes):
        """Verify git commits are created."""
        await store.put(b"test data", mime="text/plain", source_url="https://example.com")
        # Check git log has commits
        import subprocess
        result = subprocess.run(
            ["git", "log", "--oneline", "-n", "5"],
            cwd=store.repo_path,
            capture_output=True,
            text=True,
        )
        assert "Add media asset" in result.stdout