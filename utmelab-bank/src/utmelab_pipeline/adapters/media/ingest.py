"""Media ingestion: fetch, validate, store, and attach to staging items."""

import hashlib
from datetime import UTC, datetime
from typing import Optional

import httpx
from PIL import Image

from utmelab_pipeline.domain.models import MediaAsset, StagingItem
from utmelab_pipeline.domain.ports import MediaFetcher, MediaValidator, MediaStore


class HttpMediaFetcher(MediaFetcher):
    """Fetch media bytes via HTTP with size limit and timeout."""

    def __init__(
        self,
        *,
        max_bytes: int = 10_000_000,  # 10 MB
        timeout: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.max_bytes = max_bytes
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "UTME-Lab-MediaFetcher/1.0"},
        )

    async def fetch(self, url: str) -> bytes:
        resp = await self._client.get(url)
        resp.raise_for_status()
        content = resp.content
        if len(content) > self.max_bytes:
            raise ValueError(f"Media exceeds size limit ({self.max_bytes} bytes)")
        return content

    async def close(self) -> None:
        await self._client.aclose()


class PillowMediaValidator(MediaValidator):
    """Validate media using Pillow (MIME sniff, decode, dimensions)."""

    async def validate(self, data: bytes, mime: Optional[str] = None) -> MediaAsset:
        # Sniff MIME if not provided
        if mime is None:
            mime = self._sniff_mime(data)
            if mime is None:
                raise ValueError("Could not determine MIME type")

        # Decode with Pillow to validate and get dimensions
        try:
            import io
            img = Image.open(io.BytesIO(data))
            img.verify()  # Verify integrity
            img = Image.open(io.BytesIO(data))  # Reopen after verify
            width, height = img.size
            mime = mime or Image.MIME.get(img.format, mime)
        except Exception as e:
            raise ValueError(f"Invalid image data: {e}")

        # Compute hash
        asset_id = hashlib.sha256(data).hexdigest()

        return MediaAsset(
            asset_id=asset_id,
            mime=mime,
            byte_size=len(data),
            width=width,
            height=height,
            storage_url="",  # Filled in by store
            source_url=None,
            fetched_at=None,  # Filled in by store
            required=True,
            readable=True,
        )

    def _sniff_mime(self, data: bytes) -> Optional[str]:
        """Sniff MIME type from magic bytes."""
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
            return "image/gif"
        if data.startswith(b"RIFF") and b"WEBP" in data[:12]:
            return "image/webp"
        if data.startswith(b"\x00\x00\x00\x0c") and b"ftyp" in data[4:12]:
            return "image/heic"
        return None


class MediaIngestor:
    """Ingest media refs into assets and attach to staging items."""

    def __init__(
        self,
        fetcher: MediaFetcher,
        validator: MediaValidator,
        store: MediaStore,
    ) -> None:
        self.fetcher = fetcher
        self.validator = validator
        self.store = store

    async def ingest_refs(self, item: "StagingItem") -> "StagingItem":
        """Fetch and store all media refs, return updated item."""
        if not item.media_refs:
            return item

        assets = []
        for ref in item.media_refs:
            data = await self.fetcher.fetch(ref.source_url)
            asset = await self.validator.validate(data, ref.mime)
            asset = await self.store.put(
                data,
                mime=asset.mime,
                source_url=ref.source_url,
            )
            assets.append(asset)

        # Build new item with assets attached
        return item.model_copy(
            update={
                "media_assets": tuple(asset for asset in assets),
                "state": "media_ready",
                "updated_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
            }
        )


async def ingest_media_task(
    item: "StagingItem",
    fetcher: MediaFetcher,
    validator: MediaValidator,
    store: MediaStore,
) -> "StagingItem":
    """Task: ingest media refs for a staging item."""
    ingestor = MediaIngestor(fetcher, validator, store)
    return await ingestor.ingest_refs(item)