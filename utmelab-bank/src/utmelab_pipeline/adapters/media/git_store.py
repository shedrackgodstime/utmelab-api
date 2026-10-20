"""Git-backed media store with GitLab remote support."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from utmelab_pipeline.domain.models import MediaAsset
from utmelab_pipeline.domain.ports import MediaStore


class GitMediaStore(MediaStore):
    """Media store backed by a Git repository (pushable to GitLab)."""

    def __init__(
        self,
        repo_path: Path,
        remote_url: Optional[str] = None,
        branch: str = "main",
    ) -> None:
        self.repo_path = Path(repo_path)
        self.remote_url = remote_url
        self.branch = branch
        self._ensure_repo()

    def _ensure_repo(self) -> None:
        """Initialize git repo if needed."""
        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            subprocess.run(
                ["git", "init"],
                cwd=self.repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "utmelab@local"],
                cwd=self.repo_path,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "UTME Lab"],
                cwd=self.repo_path,
                check=True,
            )

    def _run_git(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            check=True,
            capture_output=True,
            text=True,
        )

    def _compute_hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _object_path(self, asset_id: str) -> Path:
        """Path to the media file in the repo (content-addressed)."""
        # First 2 chars as directory for better filesystem performance
        return self.repo_path / "objects" / asset_id[:2] / asset_id[2:]

    def _meta_path(self, asset_id: str) -> Path:
        """Path to the metadata file."""
        return self._object_path(asset_id).with_suffix(".json")

    async def put(
        self,
        data: bytes,
        *,
        mime: str,
        source_url: Optional[str] = None,
    ) -> MediaAsset:
        """Store media bytes and return the asset metadata."""
        asset_id = self._compute_hash(data)
        obj_path = self._object_path(asset_id)
        meta_path = self._meta_path(asset_id)

        # Check if already exists
        if obj_path.exists():
            meta = json.loads(meta_path.read_text())
            return MediaAsset(**meta)

        # Write the file
        obj_path.parent.mkdir(parents=True, exist_ok=True)
        obj_path.write_bytes(data)

        # Create metadata
        mime_type = mime
        width = height = None
        if mime.startswith("image/"):
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(data))
                width, height = img.size
            except Exception:
                pass

        metadata = {
            "asset_id": asset_id,
            "mime": mime_type,
            "byte_size": len(data),
            "width": width,
            "height": height,
            "storage_url": f"file://{obj_path.absolute()}",
            "source_url": source_url,
            "fetched_at": datetime.now(UTC).isoformat(),
            "required": True,
            "readable": True,
        }

        meta_path.write_text(json.dumps(metadata, indent=2))

        # Stage and commit
        self._run_git(["add", str(obj_path.relative_to(self.repo_path)), str(meta_path.relative_to(self.repo_path))])
        self._run_git(["commit", "-m", f"Add media asset {asset_id[:16]}"])

        return MediaAsset(**metadata)

    async def read(self, asset_id: str) -> bytes:
        """Read media bytes by asset ID."""
        obj_path = self._object_path(asset_id)
        if not obj_path.exists():
            raise FileNotFoundError(f"Media asset not found: {asset_id}")
        return obj_path.read_bytes()

    async def exists(self, asset_id: str) -> bool:
        """Check if asset exists."""
        return self._object_path(asset_id).exists()

    def push(self) -> None:
        """Push to remote (GitLab)."""
        if self.remote_url:
            self._run_git(["push", self.remote_url, self.branch])

    def pull(self) -> None:
        """Pull from remote (GitLab)."""
        if self.remote_url:
            self._run_git(["pull", self.remote_url, self.branch])

    def status(self) -> dict:
        """Get repository status."""
        result = self._run_git(["status", "--porcelain"])
        return {
            "clean": result.stdout.strip() == "",
            "changes": result.stdout.strip().splitlines() if result.stdout.strip() else [],
        }