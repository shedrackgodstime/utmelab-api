"""A plain local store for figures, used when no remote is configured.

It writes the same content-addressed names as the GitLab store, in the same
folder, but it publishes nothing. The row therefore keeps its source url,
because the bank cannot serve a file that only lives on this machine.

There is no clone and no git here. The folder is just a folder.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from utmelab_bank.domain.models import MediaAsset

from .errors import MediaError
from .info import dimensions
from .paths import REPO_DIR, extension_for, name_for, sha256_of

__all__ = ["LocalMediaStore"]


class LocalMediaStore:
    """Content-addressed files on local disk, not published."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()

    async def put(
        self,
        data: bytes,
        *,
        mime: str,
        source_url: str | None = None,
    ) -> MediaAsset:
        if not data:
            raise MediaError("refusing to store empty bytes")
        extension = extension_for(source_url or "", mime, data)
        digest = sha256_of(data)
        name = name_for(digest, extension)
        path = self._path(name)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        width, height = dimensions(data)
        return MediaAsset(
            asset_id=digest,
            mime=mime,
            byte_size=len(data),
            width=width,
            height=height,
            storage_url=name,
            source_url=source_url,
            fetched_at=datetime.now(UTC),
            required=True,
            readable=True,
        )

    async def read(self, name: str) -> bytes:
        path = self._path(name)
        if not path.is_file():
            raise MediaError("media asset not found", name=name)
        return path.read_bytes()

    async def exists(self, name: str) -> bool:
        return self._path(name).is_file()

    def served_url(self, name: str) -> str | None:
        return None

    def _path(self, name: str) -> Path:
        path = (self.root / REPO_DIR / name).resolve()
        anchor = (self.root / REPO_DIR).resolve()
        if anchor not in path.parents:
            raise MediaError("name escapes the store", name=name)
        return path
