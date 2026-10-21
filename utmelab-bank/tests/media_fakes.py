"""Test doubles for the media branch. No network and no disk."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from utmelab_bank.adapters.media.paths import extension_for, name_for
from utmelab_bank.domain.models import MediaAsset

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c63f8cfc0000003010100c9fe92ef0000000049454e44ae426082"
)

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


class FakeMediaFetcher:
    def __init__(self, data: bytes = PNG_1X1) -> None:
        self.data = data
        self.urls: list[str] = []

    async def fetch(self, url: str) -> bytes:
        self.urls.append(url)
        return self.data


class FailingMediaFetcher:
    def __init__(self, message: str = "the host is gone") -> None:
        self.message = message
        self.urls: list[str] = []

    async def fetch(self, url: str) -> bytes:
        self.urls.append(url)
        raise OSError(self.message)


class FakeMediaStore:
    """A store that records the bare name and decides whether it is servable.

    ``published`` is the store's answer to "can anybody fetch this?". When it
    is false the bytes are held but the row must keep its source url, which is
    the skip branch.
    """

    def __init__(
        self,
        base: str = "https://media.example/objects",
        *,
        published: bool = True,
    ) -> None:
        self.base = base.rstrip("/")
        self.published = published
        self.saved: dict[str, bytes] = {}

    async def put(self, data: bytes, *, mime: str, source_url: str | None = None) -> MediaAsset:
        asset_id = hashlib.sha256(data).hexdigest()
        name = name_for(asset_id, extension_for(source_url or "", mime, data))
        self.saved[name] = data
        return MediaAsset(
            asset_id=asset_id,
            mime=mime,
            byte_size=len(data),
            width=1,
            height=1,
            storage_url=name,
            source_url=source_url,
            fetched_at=NOW,
            required=True,
            readable=True,
        )

    async def read(self, name: str) -> bytes:
        return self.saved[name]

    async def exists(self, name: str) -> bool:
        return name in self.saved

    def served_url(self, name: str) -> str | None:
        if not self.published or not self.base:
            return None
        return f"{self.base}/{name}"


__all__ = [
    "NOW",
    "PNG_1X1",
    "FailingMediaFetcher",
    "FakeMediaFetcher",
    "FakeMediaStore",
]
